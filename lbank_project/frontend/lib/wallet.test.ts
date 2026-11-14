import assert from "node:assert/strict";
import test from "node:test";
import { transferData } from "./wallet";

test("ERC-20 transfer data encodes the exact 18-decimal amount", () => {
  const data = transferData(
    "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    49_137_000,
    18,
  );
  assert.equal(data.slice(0, 10), "0xa9059cbb");
  assert.equal(data.length, 10 + 128);
  assert.equal(
    data.slice(10, 74),
    "000000000000000000000000" + "5aaeb6053f3e94c9b9a09f33669435e7ef1beaed",
  );
  assert.equal(BigInt("0x" + data.slice(74)), 49_137_000n * 10n ** 12n);
});
