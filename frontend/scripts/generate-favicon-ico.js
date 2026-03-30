#!/usr/bin/env node
/**
 * Generates favicon.ico from executivedesk-favicon.svg (16/32/48 sizes).
 * Run: node scripts/generate-favicon-ico.js
 * Requires: npm install sharp to-ico (one-time)
 */
const fs = require('fs');
const path = require('path');

const svgPath = path.join(__dirname, '../public/executivedesk-favicon.svg');
const icoPath = path.join(__dirname, '../public/favicon.ico');

async function main() {
  let sharp, toIco;
  try {
    sharp = require('sharp');
    toIco = require('to-ico');
  } catch (e) {
    console.error('Missing deps. Run: npm install sharp to-ico --save-dev');
    process.exit(1);
  }

  const svg = fs.readFileSync(svgPath);
  const sizes = [16, 32, 48];
  const buffers = await Promise.all(
    sizes.map((size) =>
      sharp(svg).resize(size, size).png().toBuffer()
    )
  );
  const ico = await toIco(buffers, { sizes });
  fs.writeFileSync(icoPath, ico);
  console.log('Wrote', icoPath);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
