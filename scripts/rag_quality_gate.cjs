#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.RAG_GATE_BASE_URL || 'http://127.0.0.1:8000';
const ENDPOINT = process.env.RAG_GATE_ENDPOINT || '/api/v1/chat/command';
const TENANT = process.env.RAG_GATE_TENANT || 't_default';
const QUERY_TIMEOUT_MS = Number(process.env.RAG_GATE_TIMEOUT_MS || 10000);
const OUTPUT_ROOT = '/tmp';
const RUNS_DIR = path.join(OUTPUT_ROOT, 'rag_quality_runs');
const REPORT_PATH = path.join(OUTPUT_ROOT, 'rag_quality_report.json');

// Keep default suite to 5 for fast local quality gating.
const DEFAULT_QUERIES = [
  'What are the top crypto movers in the last 24h?',
  'Summarize risk constraints for live trading.',
  'How should I size a BTC buy to limit downside risk?',
  'What evidence supports buying ETH today?',
  'Explain why this trade could be rejected before execution.',
];

const FAILURE_REASON = Object.freeze({
  RATE_LIMITED_EXPRESS: 'rate_limited_express',
  RATE_LIMITED_OPENAI: 'rate_limited_openai',
  CITATION_INTEGRITY_FAIL: 'citation_integrity_fail',
  VALIDATOR_FAIL: 'validator_fail',
  STREAM_TIMEOUT: 'stream_timeout',
});

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function safeReadJson(filePath, fallback) {
  try {
    if (!fs.existsSync(filePath)) return fallback;
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch {
    return fallback;
  }
}

function appendReportRow(reportRow) {
  const existing = safeReadJson(REPORT_PATH, { generatedAt: null, runs: [] });
  const runs = Array.isArray(existing.runs) ? existing.runs : [];
  runs.push(reportRow);
  const payload = {
    generatedAt: new Date().toISOString(),
    runs,
  };
  fs.writeFileSync(REPORT_PATH, JSON.stringify(payload, null, 2));
}

function slugify(input) {
  return String(input || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60) || 'query';
}

function normalizeSourceKey(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/https?:\/\//g, '')
    .replace(/[^\w.-]+/g, '_')
    .replace(/^_+|_+$/g, '') || 'unknown';
}

function firstPresent(obj, keys, fallback = null) {
  if (!obj || typeof obj !== 'object') return fallback;
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(obj, key) && obj[key] != null) {
      return obj[key];
    }
  }
  return fallback;
}

function deepCollectByKey(root, keyMatchers, acc = []) {
  if (root == null) return acc;
  if (Array.isArray(root)) {
    for (const item of root) deepCollectByKey(item, keyMatchers, acc);
    return acc;
  }
  if (typeof root !== 'object') return acc;
  for (const [k, v] of Object.entries(root)) {
    const lk = k.toLowerCase();
    if (keyMatchers.some((m) => lk === m || lk.includes(m))) {
      acc.push(v);
    }
    deepCollectByKey(v, keyMatchers, acc);
  }
  return acc;
}

function parseBulletLines(content) {
  const lines = String(content || '')
    .split(/\r?\n/)
    .map((x) => x.trim())
    .filter(Boolean);
  return lines.filter((line) => /^([-*•]|\d+\.)\s+/.test(line));
}

function countCitations(line) {
  if (!line) return 0;
  const bracketRefs = line.match(/\[[^[\]]+\]/g) || [];
  const markdownLinks = line.match(/\[[^[\]]+\]\([^)]+\)/g) || [];
  const parenUrls = line.match(/\((https?:\/\/[^)]+)\)/g) || [];
  return bracketRefs.length + markdownLinks.length + parenUrls.length;
}

function extractRetrievedCandidates(payload) {
  const chunksArrays = deepCollectByKey(payload, ['chunks', 'candidates', 'retrieved']);
  const flattened = [];
  for (const maybeArray of chunksArrays) {
    if (Array.isArray(maybeArray)) {
      for (const item of maybeArray) {
        if (item && typeof item === 'object') flattened.push(item);
      }
    }
  }
  return flattened;
}

function extractFinalTopK(payload) {
  const arrays = deepCollectByKey(payload, ['final_topk', 'topk', 'top_k', 'selected_chunks', 'citations']);
  for (const value of arrays) {
    if (Array.isArray(value)) return value;
  }
  return [];
}

function extractSourceFromCandidate(item) {
  const sourceRaw = firstPresent(item, ['source_key', 'source', 'source_id', 'domain', 'provider'], null);
  if (sourceRaw) return normalizeSourceKey(sourceRaw);
  if (typeof item.url === 'string' && item.url.length > 0) {
    try {
      const u = new URL(item.url);
      return normalizeSourceKey(u.hostname);
    } catch {
      return normalizeSourceKey(item.url);
    }
  }
  return 'unknown';
}

function classifyFailure(status, body, elapsedMs) {
  if (elapsedMs >= QUERY_TIMEOUT_MS) return FAILURE_REASON.STREAM_TIMEOUT;
  const text = JSON.stringify(body || {}).toLowerCase();
  if (status === 429) {
    if (text.includes('openai') || text.includes('model') || text.includes('llm')) {
      return FAILURE_REASON.RATE_LIMITED_OPENAI;
    }
    return FAILURE_REASON.RATE_LIMITED_EXPRESS;
  }
  if (text.includes('citation') && (text.includes('invalid') || text.includes('integrity') || text.includes('missing'))) {
    return FAILURE_REASON.CITATION_INTEGRITY_FAIL;
  }
  if (text.includes('validator') || text.includes('validation failed')) {
    return FAILURE_REASON.VALIDATOR_FAIL;
  }
  if (text.includes('timeout')) return FAILURE_REASON.STREAM_TIMEOUT;
  return null;
}

async function postWithTimeout(url, body, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const started = Date.now();
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Dev-Tenant': TENANT,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const rawText = await response.text();
    let parsed;
    try {
      parsed = rawText ? JSON.parse(rawText) : {};
    } catch {
      parsed = { rawText };
    }
    return {
      ok: response.ok,
      status: response.status,
      body: parsed,
      elapsedMs: Date.now() - started,
    };
  } catch (err) {
    const timedOut = err && (err.name === 'AbortError' || String(err.message || '').includes('aborted'));
    return {
      ok: false,
      status: timedOut ? 408 : 500,
      body: { error: timedOut ? 'timeout' : String(err.message || err) },
      elapsedMs: Date.now() - started,
    };
  } finally {
    clearTimeout(timer);
  }
}

function buildDiagnostics(query, response) {
  const body = response.body || {};
  const diag = body.diagnostics || body.debug || {};

  const retrievalMs = Number(firstPresent(diag, ['retrievalMs', 'retrieval_ms'], 0)) || 0;
  const generationMs = Number(firstPresent(diag, ['generationMs', 'generation_ms'], 0)) || 0;
  const totalMs = Number(firstPresent(diag, ['totalMs', 'total_ms'], response.elapsedMs)) || response.elapsedMs;

  const retrievedCandidates = extractRetrievedCandidates(body);
  const finalTopKItems = extractFinalTopK(body);
  const citations = Array.isArray(body.citations) ? body.citations : [];
  const evidenceList = Array.isArray(body.evidence_links)
    ? body.evidence_links
    : (Array.isArray(body.evidence_items) ? body.evidence_items : []);

  const retrievedSourceSet = new Set(retrievedCandidates.map(extractSourceFromCandidate));
  const citedSourceSet = new Set(
    citations.map((c) => normalizeSourceKey(firstPresent(c, ['source_key', 'source', 'domain', 'provider'], 'unknown')))
  );

  const perSourceCounts = {};
  for (const item of finalTopKItems) {
    const key = extractSourceFromCandidate(item);
    perSourceCounts[key] = (perSourceCounts[key] || 0) + 1;
  }

  const contentText = String(firstPresent(body, ['content', 'answer', 'message'], ''));
  const bulletLines = parseBulletLines(contentText);
  const citationsPerBullet = bulletLines.map((line) => ({
    line,
    citations: countCitations(line),
  }));

  const evidenceListSourceKeys = evidenceList.map((item) => {
    if (item && typeof item === 'object') {
      return normalizeSourceKey(firstPresent(item, ['source_key', 'source', 'label', 'href'], 'unknown'));
    }
    return normalizeSourceKey(item);
  });

  const intent = firstPresent(body, ['intent', 'resolved_intent'], 'UNKNOWN');
  const intentScores =
    firstPresent(body, ['intentScores', 'intent_scores', 'intent_confidences'], null) ||
    firstPresent(diag, ['intentScores', 'intent_scores', 'intent_confidences'], null);

  const failureReason = classifyFailure(response.status, body, response.elapsedMs);

  return {
    query,
    timestamp: new Date().toISOString(),
    statusCode: response.status,
    ok: response.ok,
    intent,
    intentScores,
    retrievalMs,
    generationMs,
    totalMs,
    retrievedCandidatesCount: retrievedCandidates.length,
    finalTopK: finalTopKItems.length,
    uniqueSourcesRetrieved: retrievedSourceSet.size,
    uniqueSourcesCited: citedSourceSet.size,
    perSourceCounts,
    bulletLines,
    citationsPerBullet,
    evidenceListSourceKeys,
    failureReason,
  };
}

function writeRunArtifact(row, index) {
  const file = `${String(index + 1).padStart(2, '0')}_${slugify(row.query)}_${Date.now()}.json`;
  const outPath = path.join(RUNS_DIR, file);
  fs.writeFileSync(outPath, JSON.stringify(row, null, 2));
  return outPath;
}

function printCompactTable(rows) {
  const compact = rows.map((r, idx) => ({
    '#': idx + 1,
    intent: r.intent,
    ms: r.totalMs,
    retr: r.retrievalMs,
    gen: r.generationMs,
    cand: r.retrievedCandidatesCount,
    topK: r.finalTopK,
    srcR: r.uniqueSourcesRetrieved,
    srcC: r.uniqueSourcesCited,
    bullets: r.bulletLines.length,
    fail: r.failureReason || '',
  }));
  console.table(compact);
}

async function main() {
  ensureDir(RUNS_DIR);

  const queries = process.argv.slice(2).filter(Boolean);
  const runQueries = queries.length > 0 ? queries : DEFAULT_QUERIES;
  const url = `${BASE_URL}${ENDPOINT}`;

  const startedAt = Date.now();
  const rows = [];

  for (let i = 0; i < runQueries.length; i += 1) {
    const query = runQueries[i];
    const response = await postWithTimeout(
      url,
      { text: query, conversation_id: null, news_enabled: false },
      QUERY_TIMEOUT_MS
    );
    const row = buildDiagnostics(query, response);
    rows.push(row);
    appendReportRow(row);
    const artifactPath = writeRunArtifact(row, i);
    console.log(`saved: ${artifactPath}`);
  }

  printCompactTable(rows);

  const elapsed = Date.now() - startedAt;
  console.log(`report: ${REPORT_PATH}`);
  console.log(`queries: ${rows.length} total_ms: ${elapsed}`);

  if (elapsed > 60000) {
    console.error('quality gate warning: run exceeded 60s');
    process.exitCode = 2;
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

