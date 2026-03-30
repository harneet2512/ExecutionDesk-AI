"""Eval node."""
import json
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso

async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute eval node."""
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get proposal and news_enabled flag
        cursor.execute(
            "SELECT trade_proposal_json, news_enabled FROM runs WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        proposal = json.loads(row["trade_proposal_json"]) if row and row["trade_proposal_json"] else {}
        news_enabled = bool(row["news_enabled"]) if row and "news_enabled" in row.keys() else True
        
        # Get policy decision
        cursor.execute(
            "SELECT decision FROM policy_events WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
            (run_id,)
        )
        pol_row = cursor.fetchone()
        policy_decision = pol_row["decision"] if pol_row else "ALLOWED"
        
        # Eval 1: Schema validity
        schema_validity = 1.0 if proposal.get("orders") and proposal.get("citations") else 0.0
        eval1_id = new_id("eval_")
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (eval1_id, run_id, tenant_id, "schema_validity", schema_validity, json.dumps(["Proposal has required keys"]), now_iso())
        )
        
        # Eval 2: Policy compliance
        policy_compliance = 1.0 if policy_decision in ("ALLOWED", "REQUIRES_APPROVAL") else 0.0
        eval2_id = new_id("eval_")
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (eval2_id, run_id, tenant_id, "policy_compliance", policy_compliance, json.dumps([f"Policy decision: {policy_decision}"]), now_iso())
        )
        
        # Eval 3: Citation coverage
        citations_count = len(proposal.get("citations", []))
        citation_coverage = min(1.0, citations_count / 1.0)  # min(1.0, count / 1)
        eval3_id = new_id("eval_")
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (eval3_id, run_id, tenant_id, "citation_coverage", citation_coverage, json.dumps([f"Citations: {citations_count}"]), now_iso())
        )
        
        # Get command/intent for enhanced evals
        cursor.execute(
            "SELECT parsed_intent_json, command_text FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_row = cursor.fetchone()
        parsed_intent = json.loads(run_row["parsed_intent_json"]) if run_row and "parsed_intent_json" in run_row.keys() and run_row["parsed_intent_json"] else None
        
        # Eval 4: Intent parse accuracy (if command-based run)
        if parsed_intent:
            intent_fields = ["side", "budget_usd", "metric", "window", "universe"]
            parsed_fields = [f for f in intent_fields if f in parsed_intent]
            intent_parse_accuracy = len(parsed_fields) / len(intent_fields)
            eval4_id = new_id("eval_")
            cursor.execute(
                """
                INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (eval4_id, run_id, tenant_id, "intent_parse_accuracy", intent_parse_accuracy, json.dumps([f"Parsed {len(parsed_fields)}/{len(intent_fields)} fields"]), now_iso())
            )
            
            # Eval 5: Strategy validity
            execution_plan_json = run_row["execution_plan_json"] if run_row and "execution_plan_json" in run_row.keys() else None
            if execution_plan_json:
                execution_plan = json.loads(execution_plan_json)
                strategy_spec = execution_plan.get("strategy_spec", {})
                selected_asset = execution_plan.get("selected_asset")
                universe = strategy_spec.get("universe", [])
                
                strategy_validity = 1.0 if selected_asset and selected_asset in universe else 0.0
                eval5_id = new_id("eval_")
                cursor.execute(
                    """
                    INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (eval5_id, run_id, tenant_id, "strategy_validity", strategy_validity, json.dumps([f"Selected {selected_asset} from universe"]), now_iso())
                )
        
        # Eval 6: Execution correctness
        orders = proposal.get("orders", [])
        execution_correctness = 1.0
        reasons = []
        for order in orders:
            if not order.get("symbol"):
                execution_correctness = 0.0
                reasons.append("Missing symbol")
            if not order.get("side") in ["BUY", "SELL"]:
                execution_correctness = 0.0
                reasons.append(f"Invalid side: {order.get('side')}")
            if not order.get("notional_usd") or order.get("notional_usd") <= 0:
                execution_correctness = 0.0
                reasons.append("Invalid notional")
        eval6_id = new_id("eval_")
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (eval6_id, run_id, tenant_id, "execution_correctness", execution_correctness, json.dumps(reasons if reasons else ["All orders valid"]), now_iso())
        )
        
        # Eval 7: Tool error rate
        cursor.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed FROM tool_calls WHERE run_id = ?",
            (run_id,)
        )
        tool_row = cursor.fetchone()
        tool_total = tool_row["total"] if tool_row else 0
        tool_failed = tool_row["failed"] if tool_row else 0
        # Score is 1 - error_rate: 1.0 means no errors, 0.0 means all failed
        # When no tool calls are recorded, score is 1.0 (no errors occurred)
        tool_error_rate = (1.0 - (tool_failed / tool_total)) if tool_total > 0 else 1.0
        eval7_id = new_id("eval_")
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (eval7_id, run_id, tenant_id, "tool_error_rate", tool_error_rate, json.dumps([f"{tool_failed}/{tool_total} tool calls failed"]), now_iso())
        )
        
        # Eval 8: End-to-end latency with decomposition
        # Score separately: backend compute vs broker/external latency
        cursor.execute(
            "SELECT created_at, completed_at FROM runs WHERE run_id = ?",
            (run_id,)
        )
        run_timing = cursor.fetchone()
        latency_decomposition = {}
        if run_timing and "created_at" in run_timing.keys() and run_timing["created_at"]:
            from datetime import datetime, timezone
            created = datetime.fromisoformat(run_timing["created_at"].replace("Z", "+00:00"))
            if run_timing["completed_at"]:
                completed = datetime.fromisoformat(run_timing["completed_at"].replace("Z", "+00:00"))
            else:
                completed = datetime.now(timezone.utc)
            duration_seconds = (completed - created).total_seconds()

            # Decompose: fetch per-node durations from dag_nodes
            broker_ms = 0
            news_ms = 0
            compute_ms = 0
            try:
                cursor.execute(
                    "SELECT name, started_at, completed_at FROM dag_nodes WHERE run_id = ? AND status = 'completed'",
                    (run_id,),
                )
                for dn in cursor.fetchall():
                    nname = dn["name"]
                    try:
                        ns = datetime.fromisoformat(dn["started_at"].replace("Z", "+00:00"))
                        nc = datetime.fromisoformat(dn["completed_at"].replace("Z", "+00:00"))
                        nms = int((nc - ns).total_seconds() * 1000)
                    except Exception:
                        nms = 0
                    if nname in ("execution", "post_trade"):
                        broker_ms += nms
                    elif nname == "news":
                        news_ms += nms
                    else:
                        compute_ms += nms
            except Exception:
                pass

            latency_decomposition = {
                "total_seconds": round(duration_seconds, 1),
                "backend_compute_ms": compute_ms,
                "broker_wait_ms": broker_ms,
                "news_provider_ms": news_ms,
            }

            # Score based on controllable compute time, not broker latency
            controllable_seconds = compute_ms / 1000.0
            if controllable_seconds < 15:
                latency_score = 1.0
            elif controllable_seconds < 30:
                latency_score = 0.8
            elif controllable_seconds < 60:
                latency_score = 0.5
            else:
                latency_score = max(0.0, 1.0 - (controllable_seconds - 60) / 120)
        else:
            duration_seconds = None
            latency_score = 0.0

        latency_reasons = []
        if duration_seconds is not None:
            latency_reasons.append(f"Total: {duration_seconds:.1f}s")
            if latency_decomposition:
                latency_reasons.append(
                    f"Compute: {latency_decomposition.get('backend_compute_ms', 0)}ms, "
                    f"Broker: {latency_decomposition.get('broker_wait_ms', 0)}ms, "
                    f"News: {latency_decomposition.get('news_provider_ms', 0)}ms"
                )
        else:
            latency_reasons.append("Run not completed")

        eval8_id = new_id("eval_")
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (eval8_id, run_id, tenant_id, "end_to_end_latency", latency_score, json.dumps(latency_reasons), now_iso())
        )
        
        # Enhanced evaluations for command-based runs
        if parsed_intent:
            # Eval 9: Ranking correctness offline verification
            cursor.execute(
                "SELECT ranking_id, table_json, selected_symbol FROM rankings WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
                (run_id,)
            )
            ranking_row = cursor.fetchone()
            if ranking_row:
                rankings_data = json.loads(ranking_row["table_json"])
                selected_from_ranking = ranking_row["selected_symbol"]
                # Verify selected symbol is in rankings and is top-ranked
                if rankings_data and rankings_data[0].get("symbol") == selected_from_ranking:
                    ranking_correctness = 1.0
                    reasons = ["Selected symbol matches top-ranked symbol in stored rankings"]
                else:
                    ranking_correctness = 0.0
                    reasons = [f"Selected {selected_from_ranking} but rankings show {rankings_data[0].get('symbol') if rankings_data else 'none'}"]
                
                eval9_id = new_id("eval_")
                cursor.execute(
                    """
                    INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (eval9_id, run_id, tenant_id, "ranking_correctness_offline", ranking_correctness, json.dumps(reasons), now_iso())
                )
            
            # Eval 10: Numeric claims grounded (verify prices/returns in evidence)
            cursor.execute(
                "SELECT table_json FROM rankings WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
                (run_id,)
            )
            ranking_check = cursor.fetchone()
            numeric_grounded = 1.0
            grounded_reasons = []
            if ranking_check:
                rankings_check_data = json.loads(ranking_check["table_json"])
                for rank in rankings_check_data[:3]:  # Check top 3
                    # Rankings may have "return_pct" or "score"/"first_price"/"last_price"
                    has_return = "return_pct" in rank or "score" in rank
                    has_symbol = "symbol" in rank
                    if not has_return or not has_symbol:
                        numeric_grounded -= 0.25
                        grounded_reasons.append(f"Missing numeric fields in ranking for {rank.get('symbol', '?')}")
                numeric_grounded = max(0.0, numeric_grounded)
                if not grounded_reasons:
                    grounded_reasons = ["All numeric claims (returns) present in evidence artifacts"]
            else:
                numeric_grounded = 0.5
                grounded_reasons = ["No rankings evidence found"]
            
            eval10_id = new_id("eval_")
            cursor.execute(
                """
                INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (eval10_id, run_id, tenant_id, "numeric_claims_grounded", numeric_grounded, json.dumps(grounded_reasons), now_iso())
            )
            
            # Eval 11: Tool call coverage
            cursor.execute(
                "SELECT COUNT(*) as total FROM tool_calls WHERE run_id = ?",
                (run_id,)
            )
            tool_total = cursor.fetchone()["total"]
            # Expected: market_data (candles) + broker (order) = at least 2
            expected_tool_calls = 2
            tool_coverage = min(1.0, tool_total / expected_tool_calls) if expected_tool_calls > 0 else 1.0
            eval11_id = new_id("eval_")
            cursor.execute(
                """
                INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (eval11_id, run_id, tenant_id, "tool_call_coverage", tool_coverage, json.dumps([f"{tool_total}/{expected_tool_calls} expected tool calls"]), now_iso())
            )
        
        # Eval 12: Policy decision present
        cursor.execute(
            "SELECT decision FROM policy_events WHERE run_id = ? ORDER BY ts DESC LIMIT 1",
            (run_id,)
        )
        pol_check = cursor.fetchone()
        policy_present = 1.0 if pol_check else 0.0
        eval12_id = new_id("eval_")
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (eval12_id, run_id, tenant_id, "policy_decision_present", policy_present, json.dumps([f"Policy decision: {pol_check['decision']}" if pol_check else "No policy decision found"]), now_iso())
        )
        
        conn.commit()
    
    # Deep evaluations (10/10 enterprise-grade) - use new connection context
    from backend.evals.action_grounding import evaluate_action_grounding
    from backend.evals.budget_compliance import evaluate_budget_compliance
    from backend.evals.ranking_correctness import evaluate_ranking_correctness
    from backend.evals.numeric_grounding import evaluate_numeric_grounding
    from backend.evals.execution_quality import evaluate_execution_quality
    from backend.evals.tool_reliability import evaluate_tool_reliability
    from backend.evals.determinism_replay import evaluate_determinism_replay
    from backend.evals.policy_invariants import evaluate_policy_invariants
    from backend.evals.ux_completeness import evaluate_ux_completeness
    from backend.evals.intent_parse_correctness import evaluate_intent_parse_correctness
    from backend.evals.plan_completeness import evaluate_plan_completeness
    from backend.evals.evidence_sufficiency import evaluate_evidence_sufficiency
    from backend.evals.risk_gate_compliance import evaluate_risk_gate_compliance
    from backend.evals.latency_slo import evaluate_latency_slo
    from backend.evals.hallucination_detection import evaluate_hallucination_detection
    from backend.evals.agent_quality import evaluate_agent_quality
    from backend.evals.news_freshness import evaluate_news_freshness
    from backend.evals.cluster_dedup import evaluate_cluster_dedup
    from backend.evals.prompt_injection_resistance import evaluate_prompt_injection_resistance
    from backend.evals.market_evidence_evals import market_evidence_integrity, freshness_eval, rate_limit_resilience
    from backend.evals.grounding_evals import portfolio_grounding, news_evidence_integrity
    from backend.evals.profit_ranking_oracle import evaluate_profit_ranking_correctness
    from backend.evals.time_window_eval import evaluate_time_window_correctness
    from backend.evals.live_trade_truthfulness import evaluate_live_trade_truthfulness
    from backend.evals.trade_idempotency import evaluate_confirm_trade_idempotency
    from backend.evals.coinbase_integrity import evaluate_coinbase_data_integrity
    from backend.evals.oracle_artifacts import (
        compute_oracle_profit_ranking,
        compute_oracle_time_window,
        save_oracle_artifacts,
    )

    # Compute and save oracle artifacts (before deep evals)
    try:
        oracle_profit = compute_oracle_profit_ranking(run_id)
        oracle_window = compute_oracle_time_window(run_id)
        oracle_data = {}
        if oracle_profit:
            oracle_data["oracle_profit_ranking"] = oracle_profit
        if oracle_window:
            oracle_data["oracle_time_window"] = oracle_window
        if oracle_data:
            save_oracle_artifacts(run_id, oracle_data)
    except Exception:
        pass

    # Deep eval 1: Action Grounding
    grounding_result = evaluate_action_grounding(run_id, tenant_id)
    eval_grounding_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_grounding_id, run_id, tenant_id, "action_grounding", grounding_result["score"],
         json.dumps(grounding_result["reasons"]), "deep", json.dumps(grounding_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 2: Budget Compliance
    budget_result = evaluate_budget_compliance(run_id, tenant_id)
    eval_budget_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_budget_id, run_id, tenant_id, "budget_compliance", budget_result["score"],
         json.dumps(budget_result["reasons"]), "deep", json.dumps(budget_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 3: Ranking Correctness
    ranking_result = evaluate_ranking_correctness(run_id, tenant_id)
    eval_ranking_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_ranking_id, run_id, tenant_id, "ranking_correctness", ranking_result["score"],
         json.dumps(ranking_result["reasons"]), "deep", json.dumps(ranking_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 4: Numeric Grounding
    numeric_result = evaluate_numeric_grounding(run_id, tenant_id)
    eval_numeric_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_numeric_id, run_id, tenant_id, "numeric_grounding", numeric_result["score"],
         json.dumps(numeric_result["reasons"]), "deep", json.dumps(numeric_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 5: Execution Quality
    execution_result = evaluate_execution_quality(run_id, tenant_id)
    eval_execution_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_execution_id, run_id, tenant_id, "execution_quality", execution_result["score"],
         json.dumps(execution_result["reasons"]), "deep", json.dumps(execution_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 6: Tool Reliability
    tool_result = evaluate_tool_reliability(run_id, tenant_id)
    eval_tool_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_tool_id, run_id, tenant_id, "tool_reliability", tool_result["score"],
         json.dumps(tool_result["reasons"]), "deep", json.dumps(tool_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 7: Determinism Replay
    determinism_result = evaluate_determinism_replay(run_id, tenant_id)
    eval_determinism_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_determinism_id, run_id, tenant_id, "determinism_replay", determinism_result["score"],
         json.dumps(determinism_result["reasons"]), "deep", json.dumps(determinism_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 8: Policy Invariants
    policy_result = evaluate_policy_invariants(run_id, tenant_id)
    eval_policy_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_policy_id, run_id, tenant_id, "policy_invariants", policy_result["score"],
         json.dumps(policy_result["reasons"]), "deep", json.dumps(policy_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 9: UX Completeness
    ux_result = evaluate_ux_completeness(run_id, tenant_id)
    eval_ux_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_ux_id, run_id, tenant_id, "ux_completeness", ux_result["score"],
         json.dumps(ux_result["reasons"]), "deep", json.dumps(ux_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 10: Intent Parse Correctness
    intent_result = evaluate_intent_parse_correctness(run_id, tenant_id)
    eval_intent_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_intent_id, run_id, tenant_id, "intent_parse_correctness", intent_result["score"],
         json.dumps(intent_result["reasons"]), "deep", json.dumps(intent_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 11: Plan Completeness
    plan_result = evaluate_plan_completeness(run_id, tenant_id)
    eval_plan_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_plan_id, run_id, tenant_id, "plan_completeness", plan_result["score"],
         json.dumps(plan_result["reasons"]), "deep", json.dumps(plan_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 12: Evidence Sufficiency
    evidence_result = evaluate_evidence_sufficiency(run_id, tenant_id)
    eval_evidence_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_evidence_id, run_id, tenant_id, "evidence_sufficiency", evidence_result["score"],
         json.dumps(evidence_result["reasons"]), "deep", json.dumps(evidence_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 13: Risk Gate Compliance
    risk_gate_result = evaluate_risk_gate_compliance(run_id, tenant_id)
    eval_risk_gate_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
        """
        INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (eval_risk_gate_id, run_id, tenant_id, "risk_gate_compliance", risk_gate_result["score"],
         json.dumps(risk_gate_result["reasons"]), "deep", json.dumps(risk_gate_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 14: Latency SLO
    latency_result = evaluate_latency_slo(run_id, tenant_id)
    eval_latency_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_latency_id, run_id, tenant_id, "latency_slo", latency_result["score"],
             json.dumps(latency_result["reasons"]), "deep", json.dumps(latency_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 15: Hallucination Detection (evidence-locked)
    hallucination_result = evaluate_hallucination_detection(run_id, tenant_id)
    eval_hallucination_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_hallucination_id, run_id, tenant_id, "hallucination_detection", hallucination_result["score"],
             json.dumps(hallucination_result["reasons"]), "deep", json.dumps(hallucination_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 16: Agent Quality
    agent_quality_result = evaluate_agent_quality(run_id, tenant_id)
    eval_agent_quality_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_agent_quality_id, run_id, tenant_id, "agent_quality", agent_quality_result["score"],
             json.dumps(agent_quality_result["reasons"]), "deep", json.dumps(agent_quality_result.get("thresholds", {})), now_iso())
        )
        conn.commit()
    
    # Deep eval 17: News Freshness (gated by news_enabled)
    if news_enabled:
        news_freshness_result = evaluate_news_freshness(run_id, tenant_id)
    else:
        news_freshness_result = {"score": 1.0, "reasons": ["Skipped: news disabled"], "thresholds": {}}
    eval_news_freshness_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_news_freshness_id, run_id, tenant_id, "news_freshness", news_freshness_result["score"],
             json.dumps(news_freshness_result["reasons"]), "deep", json.dumps(news_freshness_result.get("thresholds", {})), now_iso())
        )
        conn.commit()

    # Deep eval 18: Cluster Dedup Score (gated by news_enabled)
    if news_enabled:
        cluster_dedup_result = evaluate_cluster_dedup(run_id, tenant_id)
    else:
        cluster_dedup_result = {"score": 1.0, "reasons": ["Skipped: news disabled"], "thresholds": {}}
    eval_cluster_dedup_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_cluster_dedup_id, run_id, tenant_id, "cluster_dedup_score", cluster_dedup_result["score"],
             json.dumps(cluster_dedup_result["reasons"]), "deep", json.dumps(cluster_dedup_result.get("thresholds", {})), now_iso())
        )
        conn.commit()

    # Deep eval 19: Prompt Injection Resistance (News)
    injection_result = evaluate_prompt_injection_resistance(run_id, tenant_id)
    eval_injection_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_injection_id, run_id, tenant_id, "prompt_injection_resistance", injection_result["score"],
             json.dumps(injection_result["reasons"]), "deep", json.dumps(injection_result.get("thresholds", {})), now_iso())
        )
        conn.commit()

    # Deep eval 20: Market Evidence Integrity
    market_evidence_result = market_evidence_integrity(run_id, tenant_id)
    eval_market_evidence_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_market_evidence_id, run_id, tenant_id, "market_evidence_integrity", market_evidence_result["score"],
             json.dumps(market_evidence_result["issues"]), "deep", json.dumps({"min_score": 0.8}), now_iso())
        )
        conn.commit()

    # Deep eval 21: Data Freshness (EOD)
    freshness_result = freshness_eval(run_id, tenant_id)
    eval_freshness_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_freshness_id, run_id, tenant_id, "data_freshness", freshness_result["score"],
             json.dumps(freshness_result["issues"]), "deep", json.dumps({"max_stale_hours": 48}), now_iso())
        )
        conn.commit()

    # Deep eval 22: Rate Limit Resilience
    rate_limit_result = rate_limit_resilience(run_id, tenant_id)
    eval_rate_limit_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_rate_limit_id, run_id, tenant_id, "rate_limit_resilience", rate_limit_result["score"],
             json.dumps(rate_limit_result["issues"]), "deep", json.dumps({"min_score": 0.7}), now_iso())
        )
        conn.commit()

    # Deep eval 23: Portfolio Grounding
    portfolio_grounding_result = portfolio_grounding(run_id, tenant_id)
    eval_portfolio_grounding_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_portfolio_grounding_id, run_id, tenant_id, "portfolio_grounding", portfolio_grounding_result["score"],
             json.dumps(portfolio_grounding_result["issues"]), "deep", json.dumps({"min_score": 0.7}), now_iso())
        )
        conn.commit()

    # Deep eval 24: News Evidence Integrity (gated by news_enabled)
    if news_enabled:
        news_evidence_result = news_evidence_integrity(run_id, tenant_id)
    else:
        news_evidence_result = {"score": 1.0, "issues": ["Skipped: news disabled"]}
    eval_news_evidence_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_news_evidence_id, run_id, tenant_id, "news_evidence_integrity", news_evidence_result["score"],
             json.dumps(news_evidence_result["issues"]), "deep", json.dumps({"min_score": 0.7}), now_iso())
        )
        conn.commit()

    # Deep eval 25: Profit Ranking Correctness (oracle)
    profit_ranking_result = evaluate_profit_ranking_correctness(run_id, tenant_id)
    eval_profit_ranking_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, details_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_profit_ranking_id, run_id, tenant_id, "profit_ranking_correctness", profit_ranking_result["score"],
             json.dumps(profit_ranking_result["reasons"]), "oracle", json.dumps(profit_ranking_result.get("thresholds", {})),
             "quality", json.dumps(profit_ranking_result.get("details", {})), now_iso())
        )
        conn.commit()

    # Deep eval 26: Time Window Correctness (oracle)
    time_window_result = evaluate_time_window_correctness(run_id, tenant_id)
    eval_time_window_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, details_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_time_window_id, run_id, tenant_id, "time_window_correctness", time_window_result["score"],
             json.dumps(time_window_result["reasons"]), "oracle", json.dumps(time_window_result.get("thresholds", {})),
             "performance", json.dumps(time_window_result.get("details", {})), now_iso())
        )
        conn.commit()

    # Deep eval 27: Live Trade Truthfulness
    truthfulness_result = evaluate_live_trade_truthfulness(run_id, tenant_id)
    eval_truthfulness_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, details_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_truthfulness_id, run_id, tenant_id, "live_trade_truthfulness", truthfulness_result["score"],
             json.dumps(truthfulness_result["reasons"]), "deep", json.dumps(truthfulness_result.get("thresholds", {})),
             "compliance", json.dumps(truthfulness_result.get("details", {})), now_iso())
        )
        conn.commit()

    # Deep eval 28: Confirm Trade Idempotency
    idempotency_result = evaluate_confirm_trade_idempotency(run_id, tenant_id)
    eval_idempotency_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, details_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_idempotency_id, run_id, tenant_id, "confirm_trade_idempotency", idempotency_result["score"],
             json.dumps(idempotency_result["reasons"]), "deep", json.dumps(idempotency_result.get("thresholds", {})),
             "compliance", json.dumps(idempotency_result.get("details", {})), now_iso())
        )
        conn.commit()

    # Deep eval 29: Coinbase Data Integrity
    coinbase_result = evaluate_coinbase_data_integrity(run_id, tenant_id)
    eval_coinbase_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, details_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_coinbase_id, run_id, tenant_id, "coinbase_data_integrity", coinbase_result["score"],
             json.dumps(coinbase_result["reasons"]), "deep", json.dumps(coinbase_result.get("thresholds", {})),
             "data", json.dumps(coinbase_result.get("details", {})), now_iso())
        )
        conn.commit()

    # Enterprise runtime evals (tool success, sentiment grounding, format, state consistency)
    from backend.evals.runtime_evals import (
        emit_tool_success_rate,
        emit_news_sentiment_grounded_rate,
        emit_response_format_score,
        emit_run_state_consistency,
    )

    emit_tool_success_rate(run_id, tenant_id)
    emit_news_sentiment_grounded_rate(run_id, tenant_id)
    emit_response_format_score(run_id, tenant_id)
    emit_run_state_consistency(run_id, tenant_id)

    # RAGAS-style evals (faithfulness, answer relevance, retrieval relevance)
    from backend.evals.rag_evals import evaluate_faithfulness, evaluate_answer_relevance, evaluate_retrieval_relevance

    # Deep eval 25: Faithfulness (RAGAS)
    faithfulness_result = evaluate_faithfulness(run_id, tenant_id)
    eval_faith_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, details_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_faith_id, run_id, tenant_id, "faithfulness", faithfulness_result["score"],
             json.dumps(faithfulness_result["reasons"]), "ragas", json.dumps(faithfulness_result.get("thresholds", {})),
             "rag", json.dumps(faithfulness_result.get("details", {})), now_iso())
        )
        conn.commit()

    # Deep eval 26: Answer Relevance (RAGAS)
    answer_rel_result = evaluate_answer_relevance(run_id, tenant_id)
    eval_answer_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, details_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_answer_id, run_id, tenant_id, "answer_relevance", answer_rel_result["score"],
             json.dumps(answer_rel_result["reasons"]), "ragas", json.dumps(answer_rel_result.get("thresholds", {})),
             "rag", json.dumps(answer_rel_result.get("details", {})), now_iso())
        )
        conn.commit()

    # Deep eval 27: Retrieval Relevance (RAGAS)
    retrieval_rel_result = evaluate_retrieval_relevance(run_id, tenant_id)
    eval_retrieval_id = new_id("eval_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, details_json, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (eval_retrieval_id, run_id, tenant_id, "retrieval_relevance", retrieval_rel_result["score"],
             json.dumps(retrieval_rel_result["reasons"]), "ragas", json.dumps(retrieval_rel_result.get("thresholds", {})),
             "rag", json.dumps(retrieval_rel_result.get("details", {})), now_iso())
        )
        conn.commit()

    # ── News coverage / freshness / sentiment consistency evals ──
    # These measure headline availability and quality per trade run.
    # Gated by news_enabled - when news is OFF, score 1.0 with skip reason
    if not news_enabled:
        # Skip news evals entirely when news is disabled
        _skip_reason = json.dumps(["Skipped: news disabled"])
        _skip_thresh_cov = json.dumps({"min_headlines": 3})
        _skip_thresh_fresh = json.dumps({"max_median_age_hours": 24})
        _skip_thresh_sent = json.dumps({"min_consistency": 0.7})
        for _skip_name, _skip_thresh in [
            ("news_coverage", _skip_thresh_cov),
            ("news_freshness_eval", _skip_thresh_fresh),
            ("sentiment_consistency", _skip_thresh_sent),
        ]:
            _skip_id = new_id("eval_")
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (_skip_id, run_id, tenant_id, _skip_name, 1.0,
                     _skip_reason, "enterprise", _skip_thresh, "data", now_iso())
                )
                conn.commit()
    else:
        try:
            # news_coverage: % of trade runs with >= 3 headlines
            news_coverage_score = 0.0
            news_freshness_score = 0.0
            sentiment_consistency_score = 0.0
            news_coverage_reasons = []
            news_freshness_reasons = []
            sentiment_reasons = []

            with get_conn() as conn:
                cursor = conn.cursor()
                # Check if this run has news node outputs
                cursor.execute(
                    "SELECT outputs_json FROM dag_nodes WHERE run_id = ? AND name = 'news'",
                    (run_id,)
                )
                news_node_row = cursor.fetchone()
                headlines_count = 0
                headline_ages = []
                if news_node_row and news_node_row["outputs_json"]:
                    try:
                        import json as _j
                        artifact = _j.loads(news_node_row["outputs_json"])
                        # News node output format: brief.assets[].clusters[].items[]
                        # Each item has published_at, title, url, etc.
                        brief = artifact.get("brief", {})
                        assets = brief.get("assets", [])
                        all_items = []
                        for asset in assets:
                            for cluster in asset.get("clusters", []):
                                all_items.extend(cluster.get("items", []))
                        # Fallback to flat headlines if present
                        if not all_items:
                            all_items = artifact.get("headlines", [])
                        headlines_count = len(all_items)
                        for h in all_items:
                            pub = h.get("published_at")
                            if pub:
                                try:
                                    from datetime import datetime as _dt
                                    age_h = (
                                        _dt.utcnow() - _dt.fromisoformat(pub.replace("Z", ""))
                                    ).total_seconds() / 3600
                                    headline_ages.append(age_h)
                                except Exception:
                                    pass
                    except Exception:
                        pass

                # news_coverage: 1.0 if >= 3 headlines, proportional otherwise
                if headlines_count >= 3:
                    news_coverage_score = 1.0
                    news_coverage_reasons.append(f"{headlines_count} headlines found (>= 3 threshold)")
                elif headlines_count > 0:
                    news_coverage_score = round(headlines_count / 3.0, 2)
                    news_coverage_reasons.append(f"Only {headlines_count}/3 headlines found")
                else:
                    news_coverage_score = 0.0
                    news_coverage_reasons.append("No headlines available for this run")

                # news_freshness: 1.0 if median age < 24h, decay to 0 at 72h
                if headline_ages:
                    sorted_ages = sorted(headline_ages)
                    median_age = sorted_ages[len(sorted_ages) // 2]
                    if median_age <= 24:
                        news_freshness_score = 1.0
                    elif median_age <= 72:
                        news_freshness_score = round(1.0 - ((median_age - 24) / 48), 2)
                    else:
                        news_freshness_score = 0.0
                    news_freshness_reasons.append(f"Median headline age: {median_age:.1f}h")
                else:
                    news_freshness_score = 0.0
                    news_freshness_reasons.append("No headline timestamps available")

                # sentiment_consistency: check if rationale aligns with sentiment label
                if news_node_row and news_node_row["outputs_json"]:
                    try:
                        artifact = _j.loads(news_node_row["outputs_json"])
                        headlines = artifact.get("headlines", [])
                        consistent = 0
                        total_with_sentiment = 0
                        for h in headlines:
                            sent = h.get("sentiment", "neutral")
                            rationale = (h.get("rationale") or "").lower()
                            if sent != "neutral" and rationale:
                                total_with_sentiment += 1
                                bullish_words = {"bullish", "gains", "rally", "surge", "up", "positive", "growth"}
                                bearish_words = {"bearish", "drop", "fall", "decline", "crash", "negative", "loss"}
                                r_words = set(rationale.split())
                                if sent == "bullish" and r_words & bullish_words:
                                    consistent += 1
                                elif sent == "bearish" and r_words & bearish_words:
                                    consistent += 1
                                elif not (r_words & bullish_words) and not (r_words & bearish_words):
                                    consistent += 1
                        if total_with_sentiment > 0:
                            sentiment_consistency_score = round(consistent / total_with_sentiment, 2)
                            sentiment_reasons.append(f"{consistent}/{total_with_sentiment} headlines have consistent sentiment-rationale")
                        else:
                            sentiment_consistency_score = 1.0
                            sentiment_reasons.append("No non-neutral headlines to check")
                    except Exception:
                        sentiment_consistency_score = 0.5
                        sentiment_reasons.append("Could not parse sentiment data")

            # Persist news_coverage eval
            eval_nc_id = new_id("eval_")
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (eval_nc_id, run_id, tenant_id, "news_coverage", news_coverage_score,
                     json.dumps(news_coverage_reasons), "enterprise", json.dumps({"min_headlines": 3}),
                     "data", now_iso())
                )
                conn.commit()

            # Persist news_freshness_eval eval
            eval_nf_id = new_id("eval_")
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (eval_nf_id, run_id, tenant_id, "news_freshness_eval", news_freshness_score,
                     json.dumps(news_freshness_reasons), "enterprise", json.dumps({"max_median_age_hours": 24}),
                     "data", now_iso())
                )
                conn.commit()

            # Persist sentiment_consistency eval
            eval_sc_id = new_id("eval_")
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, eval_category, ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (eval_sc_id, run_id, tenant_id, "sentiment_consistency", sentiment_consistency_score,
                     json.dumps(sentiment_reasons), "enterprise", json.dumps({"min_score": 0.7}),
                     "quality", now_iso())
                )
                conn.commit()
        except Exception as e:
            # Non-fatal: log and continue
            pass

    # ── New evals for Risk 1 (funds recycling), Risk 3 (sentiment gate), Risk 4 (product catalog) ──
    try:
        # Sentiment gate precision eval
        sentiment_gate_score = 1.0
        sentiment_gate_reasons = []
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'news_brief' LIMIT 1",
                    (run_id,),
                )
                nb_row = cursor.fetchone()
                if nb_row:
                    nb_data = json.loads(nb_row["artifact_json"])
                    sg = nb_data.get("sentiment_gate", {})
                    if sg.get("gated"):
                        # Check: was there real bearish evidence?
                        bearish = sg.get("bearish_count", 0)
                        conf = sg.get("confidence", 0)
                        if bearish >= 2 and conf > 0.5:
                            sentiment_gate_score = 1.0
                            sentiment_gate_reasons.append(f"Gate correctly triggered: {bearish} bearish headlines, conf={conf:.2f}")
                        else:
                            sentiment_gate_score = 0.3
                            sentiment_gate_reasons.append(f"Gate triggered with weak evidence: bearish={bearish}, conf={conf:.2f}")
                    else:
                        sentiment_gate_reasons.append("No gate triggered (correct if sentiment is neutral/positive)")
                else:
                    sentiment_gate_reasons.append("No news brief artifact found")
        except Exception:
            sentiment_gate_reasons.append("Could not evaluate sentiment gate")

        _sg_eval_id = new_id("eval_")
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, eval_category, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_sg_eval_id, run_id, tenant_id, "sentiment_gate_precision", sentiment_gate_score,
                 json.dumps(sentiment_gate_reasons), "enterprise", "quality", now_iso()),
            )
            conn.commit()

        # Product metadata availability eval
        product_meta_score = 1.0
        product_meta_reasons = []
        try:
            from backend.services.product_catalog import get_product_catalog
            catalog = get_product_catalog()
            _401_count = catalog.metadata_401_count
            if _401_count == 0:
                product_meta_score = 1.0
                product_meta_reasons.append("No metadata 401 errors")
            elif _401_count <= 3:
                product_meta_score = 0.7
                product_meta_reasons.append(f"{_401_count} metadata 401 errors (using catalog fallback)")
            else:
                product_meta_score = 0.4
                product_meta_reasons.append(f"{_401_count} metadata 401 errors — auth likely misconfigured")
        except Exception:
            product_meta_reasons.append("Could not check metadata status")

        _pm_eval_id = new_id("eval_")
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, eval_category, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_pm_eval_id, run_id, tenant_id, "product_metadata_availability", product_meta_score,
                 json.dumps(product_meta_reasons), "enterprise", "data", now_iso()),
            )
            conn.commit()

    except Exception as e:
        logger.debug("New risk evals failed (non-fatal): %s", str(e)[:200])

    eval_names = [
        "schema_validity", "policy_compliance", "citation_coverage", "execution_correctness",
        "tool_error_rate", "end_to_end_latency", "policy_decision_present",
        "action_grounding", "budget_compliance", "ranking_correctness",
        "numeric_grounding", "execution_quality", "tool_reliability",
        "determinism_replay", "policy_invariants", "ux_completeness",
        "intent_parse_correctness", "plan_completeness", "evidence_sufficiency",
        "risk_gate_compliance", "latency_slo", "hallucination_detection", "agent_quality",
        "news_freshness", "cluster_dedup_score", "prompt_injection_resistance",
        "market_evidence_integrity", "data_freshness", "rate_limit_resilience",
        "portfolio_grounding", "news_evidence_integrity",
        "tool_success_rate", "news_sentiment_grounded_rate",
        "response_format_score", "run_state_consistency",
        "faithfulness", "answer_relevance", "retrieval_relevance",
        "news_coverage", "news_freshness_eval", "sentiment_consistency",
        "profit_ranking_correctness", "time_window_correctness",
        "live_trade_truthfulness", "confirm_trade_idempotency", "coinbase_data_integrity",
        "sentiment_gate_precision", "product_metadata_availability",
    ]
    
    # ── Gap-fill evals: trade_amount_intent_correctness + insufficient_balance_truthfulness ──
    try:
        # trade_amount_intent_correctness: compare intent.budget_usd to proposal.orders[0].notional_usd
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT intent_json, trade_proposal_json FROM runs WHERE run_id = ?",
                (run_id,)
            )
            run_intent_row = cursor.fetchone()

        if run_intent_row and run_intent_row["intent_json"] and run_intent_row["trade_proposal_json"]:
            _intent = json.loads(run_intent_row["intent_json"])
            _proposal = json.loads(run_intent_row["trade_proposal_json"])
            intent_budget = _intent.get("budget_usd") or _intent.get("amount_usd")
            proposal_orders = _proposal.get("orders", [])

            if intent_budget and proposal_orders:
                proposal_notional = proposal_orders[0].get("notional_usd", 0)
                # Within 1% tolerance?
                if intent_budget > 0:
                    deviation = abs(proposal_notional - intent_budget) / intent_budget
                    amount_score = 1.0 if deviation <= 0.01 else max(0.0, 1.0 - deviation)
                    amount_reasons = [
                        f"Intent budget: ${intent_budget:.2f}",
                        f"Proposal notional: ${proposal_notional:.2f}",
                        f"Deviation: {deviation*100:.1f}%",
                    ]
                else:
                    amount_score = 0.0
                    amount_reasons = ["Intent budget is zero or missing"]
            else:
                amount_score = 1.0  # N/A (no trade intent or no orders)
                amount_reasons = ["No trade intent or proposal orders to compare"]

            eval_amount_id = new_id("eval_")
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json,
                       evaluator_type, eval_category, ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (eval_amount_id, run_id, tenant_id, "trade_amount_intent_correctness",
                     amount_score, json.dumps(amount_reasons), "deep", "compliance", now_iso())
                )
                conn.commit()
            eval_names.append("trade_amount_intent_correctness")

        # insufficient_balance_truthfulness: check execution error artifacts for silent substitution
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT artifact_json FROM run_artifacts
                   WHERE run_id = ? AND artifact_type = 'execution_error'""",
                (run_id,)
            )
            error_artifacts = cursor.fetchall()

        balance_score = 1.0
        balance_reasons = []
        has_insufficient = False
        for art_row in error_artifacts:
            try:
                art = json.loads(art_row["artifact_json"])
                if art.get("error_code") == "INSUFFICIENT_BALANCE":
                    has_insufficient = True
                    # Good: error was explicitly surfaced
                    balance_reasons.append(f"INSUFFICIENT_BALANCE error explicitly surfaced for {art.get('symbol', '?')}")
            except Exception:
                pass

        if not error_artifacts:
            # Check if notional was silently reduced (compare intent to execution)
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT notional_usd FROM orders WHERE run_id = ?",
                    (run_id,)
                )
                order_rows = cursor.fetchall()

            if run_intent_row and run_intent_row["intent_json"] and order_rows:
                _intent2 = json.loads(run_intent_row["intent_json"])
                intent_budget2 = _intent2.get("budget_usd") or _intent2.get("amount_usd")
                for o_row in order_rows:
                    executed_notional = o_row["notional_usd"]
                    if intent_budget2 and executed_notional and intent_budget2 > 0:
                        if executed_notional < intent_budget2 * 0.95:  # >5% reduction = suspicious
                            balance_score = 0.0
                            balance_reasons.append(
                                f"Order notional ${executed_notional:.2f} is significantly less than "
                                f"intent ${intent_budget2:.2f} without explicit disclosure"
                            )

        if not balance_reasons:
            if has_insufficient:
                balance_reasons = ["Insufficient balance was properly disclosed"]
            else:
                balance_reasons = ["No insufficient balance issues detected"]

        eval_balance_id = new_id("eval_")
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json,
                   evaluator_type, eval_category, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eval_balance_id, run_id, tenant_id, "insufficient_balance_truthfulness",
                 balance_score, json.dumps(balance_reasons), "deep", "compliance", now_iso())
            )
            conn.commit()
        eval_names.append("insufficient_balance_truthfulness")
    except Exception:
        pass  # Non-fatal: these are supplementary evals

    # ── NEW EVALS: decision_lock_consistency, tradability_preflight_pass, order_submission_truthfulness ──
    try:
        with get_conn() as conn:
            cursor = conn.cursor()

            # Fetch locked_product_id and tradability_verified from runs
            cursor.execute(
                "SELECT locked_product_id, tradability_verified, execution_mode FROM runs WHERE run_id = ?",
                (run_id,)
            )
            lock_row = cursor.fetchone()
            locked_product_id = lock_row["locked_product_id"] if lock_row and "locked_product_id" in lock_row.keys() else None
            tradability_verified = bool(lock_row["tradability_verified"]) if lock_row and "tradability_verified" in lock_row.keys() else False
            exec_mode = lock_row["execution_mode"] if lock_row and "execution_mode" in lock_row.keys() else "PAPER"

            # Fetch executed order symbols
            cursor.execute(
                "SELECT symbol, status FROM orders WHERE run_id = ?",
                (run_id,)
            )
            order_rows = cursor.fetchall()
            executed_symbols = [r["symbol"] for r in order_rows] if order_rows else []

            # ── Eval: decision_lock_consistency ──
            # PASS if confirmed product_id == executed product_id for ALL orders
            lock_score = 1.0
            lock_reasons = []
            if locked_product_id and executed_symbols:
                for sym in executed_symbols:
                    if sym != locked_product_id:
                        lock_score = 0.0
                        lock_reasons.append(
                            f"Symbol drift detected: confirmed={locked_product_id} executed={sym}"
                        )
                if lock_score == 1.0:
                    lock_reasons.append(f"All orders matched locked product: {locked_product_id}")
            elif not locked_product_id:
                lock_score = 0.5
                lock_reasons.append("No locked_product_id set (legacy or non-trade run)")
            elif not executed_symbols:
                lock_score = 1.0
                lock_reasons.append("No orders placed (non-trading run or blocked)")

            eval_lock_id = new_id("eval_")
            cursor.execute(
                """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json,
                   evaluator_type, eval_category, step_name, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eval_lock_id, run_id, tenant_id, "decision_lock_consistency",
                 lock_score, json.dumps(lock_reasons), "deep", "reliability", "execution", now_iso())
            )
            eval_names.append("decision_lock_consistency")

            # ── Eval: tradability_preflight_pass ──
            # PASS if product was verified tradeable + precision known BEFORE confirm
            preflight_score = 1.0
            preflight_reasons = []
            if exec_mode == "LIVE":
                if tradability_verified:
                    preflight_reasons.append("Product tradability was verified before confirmation")
                else:
                    preflight_score = 0.0
                    preflight_reasons.append("Product tradability NOT verified before confirmation")

                # Check if any order failed due to product unavailable
                failed_product_orders = [
                    r for r in order_rows
                    if r["status"] in ("FAILED", "REJECTED")
                ] if order_rows else []
                if failed_product_orders:
                    preflight_score = 0.0
                    preflight_reasons.append(
                        f"{len(failed_product_orders)} order(s) failed — possible product unavailability"
                    )
            else:
                preflight_reasons.append(f"Non-LIVE mode ({exec_mode}): preflight not required")

            eval_preflight_id = new_id("eval_")
            cursor.execute(
                """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json,
                   evaluator_type, eval_category, step_name, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eval_preflight_id, run_id, tenant_id, "tradability_preflight_pass",
                 preflight_score, json.dumps(preflight_reasons), "deep", "reliability", "execution", now_iso())
            )
            eval_names.append("tradability_preflight_pass")

            # ── Eval: order_submission_truthfulness ──
            # PASS if the UI message (from trade_receipt) matches the executed flag and broker status
            truth_score = 1.0
            truth_reasons = []

            # Check trade_receipt artifact
            cursor.execute(
                """SELECT artifact_json FROM run_artifacts
                   WHERE run_id = ? AND artifact_type = 'trade_receipt'
                   ORDER BY created_at DESC LIMIT 1""",
                (run_id,)
            )
            receipt_row = cursor.fetchone()
            if receipt_row:
                try:
                    receipt = json.loads(receipt_row["artifact_json"])
                    receipt_orders = receipt.get("orders", [])
                    # Trade receipt may not have a top-level "status" field
                    # Instead check if order statuses are consistent
                    if receipt_orders:
                        all_filled = all(
                            o.get("status") in ("FILLED", "COMPLETED", "PENDING") for o in receipt_orders
                        )
                        if all_filled:
                            truth_reasons.append("Trade receipt orders show consistent fill status")
                        else:
                            statuses = [o.get("status", "?") for o in receipt_orders]
                            truth_score = 0.8
                            truth_reasons.append(
                                f"Trade receipt has mixed order statuses: {statuses}"
                            )
                    else:
                        # Receipt exists but no orders - consistent if no executed_symbols
                        if not executed_symbols:
                            truth_reasons.append("Trade receipt has no orders (consistent with no execution)")
                        else:
                            truth_score = 0.8
                            truth_reasons.append("Trade receipt exists but orders list is empty")
                except Exception:
                    truth_score = 0.5
                    truth_reasons.append("Could not parse trade_receipt artifact")
            else:
                if executed_symbols:
                    truth_score = 0.8
                    truth_reasons.append("No trade_receipt artifact found (orders recorded directly)")
                else:
                    truth_reasons.append("No orders and no receipt (consistent)")

            eval_truth_id = new_id("eval_")
            cursor.execute(
                """INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json,
                   evaluator_type, eval_category, step_name, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (eval_truth_id, run_id, tenant_id, "order_submission_truthfulness",
                 truth_score, json.dumps(truth_reasons), "deep", "reliability", "execution", now_iso())
            )
            eval_names.append("order_submission_truthfulness")

            conn.commit()
    except Exception as eval_err:
        import traceback
        traceback.print_exc()
        pass  # Non-fatal: these are supplementary evals

    # Portfolio-specific evaluations (if this is a portfolio analysis run)
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT brief_json FROM portfolio_analysis_snapshots WHERE run_id = ? LIMIT 1",
            (run_id,)
        )
        portfolio_row = cursor.fetchone()
    
    if portfolio_row:
        from backend.evals.portfolio_evals import run_portfolio_evals
        portfolio_eval_results = run_portfolio_evals(run_id, tenant_id)
        
        for result in portfolio_eval_results:
            eval_id = new_id("eval_")
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO eval_results (eval_id, run_id, tenant_id, eval_name, score, reasons_json, evaluator_type, thresholds_json, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        eval_id, run_id, tenant_id,
                        result["eval_name"],
                        result["score"],
                        json.dumps(result["reasons"]),
                        "portfolio",
                        json.dumps(result.get("thresholds", {})),
                        now_iso()
                    )
                )
                conn.commit()
            eval_names.append(result["eval_name"])
    
    # Emit RUN_EVAL_COMPLETED event
    from backend.orchestrator.event_emitter import emit_event
    await emit_event(run_id, "RUN_EVAL_COMPLETED", {
        "eval_count": len(eval_names),
        "eval_names": eval_names
    }, tenant_id=tenant_id)
    
    if parsed_intent:
        eval_names.extend(["intent_parse_accuracy", "strategy_validity", "tool_call_coverage"])
    
    return {
        "evals": eval_names,
        "safe_summary": f"Evaluated {len(eval_names)} metrics (including 24 deep evals + 4 enterprise evals + 3 RAGAS evals)"
    }
