"use strict";

// Plotly exports pixel dimensions; the PNG density chunk records the intended print size.
function setPngDpi(png, dpi) {
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (png.length < 33 || !signature.every((byte, i) => png[i] === byte)) {
    throw new Error("Некорректный PNG");
  }

  const u32 = (value) => new Uint8Array([
    (value >>> 24) & 255, (value >>> 16) & 255, (value >>> 8) & 255, value & 255,
  ]);
  const readU32 = (offset) => ((png[offset] * 0x1000000) +
    (png[offset + 1] << 16) + (png[offset + 2] << 8) + png[offset + 3]) >>> 0;
  const typeAt = (offset) => String.fromCharCode(...png.subarray(offset + 4, offset + 8));
  const density = Math.round(dpi / 0.0254);
  const chunkData = new Uint8Array(9);
  chunkData.set(u32(density), 0);
  chunkData.set(u32(density), 4);
  chunkData[8] = 1;

  const type = new Uint8Array([112, 72, 89, 115]); // pHYs
  let crc = 0xffffffff;
  for (const byte of [...type, ...chunkData]) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  const phys = new Uint8Array(21);
  phys.set(u32(9), 0);
  phys.set(type, 4);
  phys.set(chunkData, 8);
  phys.set(u32((crc ^ 0xffffffff) >>> 0), 17);

  const parts = [png.subarray(0, 8)];
  let foundHeader = false;
  for (let offset = 8; offset < png.length;) {
    const end = offset + readU32(offset) + 12;
    if (end > png.length) throw new Error("Некорректный PNG");
    const chunkType = typeAt(offset);
    if (chunkType !== "pHYs") parts.push(png.subarray(offset, end));
    if (chunkType === "IHDR") { parts.push(phys); foundHeader = true; }
    offset = end;
  }
  if (!foundHeader) throw new Error("Некорректный PNG");
  const result = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of parts) { result.set(part, offset); offset += part.length; }
  return result;
}

if (typeof module !== "undefined" && module.exports) module.exports = { setPngDpi };
else globalThis.setPngDpi = setPngDpi;
