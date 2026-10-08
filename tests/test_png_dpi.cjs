const assert = require('node:assert/strict');
const test = require('node:test');
const { setPngDpi } = require('../static/png-dpi.js');

const tinyPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/+ukAAAAASUVORK5CYII=',
  'base64'
);

function chunks(bytes) {
  const found = [];
  for (let offset = 8; offset < bytes.length;) {
    const size = Buffer.from(bytes.subarray(offset, offset + 4)).readUInt32BE();
    const type = Buffer.from(bytes.subarray(offset + 4, offset + 8)).toString('ascii');
    found.push({ type, data: bytes.subarray(offset + 8, offset + 8 + size) });
    offset += size + 12;
  }
  return found;
}

test('PNG export contains one 300 DPI pHYs chunk and keeps the image data', () => {
  const rendered = setPngDpi(tinyPng, 300);
  const parts = chunks(rendered);
  assert.deepEqual(parts.map((part) => part.type), ['IHDR', 'pHYs', 'IDAT', 'IEND']);
  const density = Buffer.from(parts[1].data);
  assert.equal(density.readUInt32BE(0), 11811);
  assert.equal(density.readUInt32BE(4), 11811);
  assert.equal(density[8], 1);
  assert.deepEqual(Buffer.from(parts[2].data), Buffer.from(chunks(tinyPng)[1].data));
});

test('PNG export replaces existing density metadata instead of duplicating it', () => {
  const once = setPngDpi(tinyPng, 300);
  const twice = setPngDpi(once, 300);
  assert.equal(chunks(twice).filter((part) => part.type === 'pHYs').length, 1);
});
