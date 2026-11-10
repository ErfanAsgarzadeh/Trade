"use strict";
// Cache only the public offline screen. Authenticated pages and API responses
// always use the network: never leave private balances/licenses on a shared device.
const CACHE = "trade-offline-v1";
const OFFLINE = "/portal-assets/offline.html";
self.addEventListener("install", (event) =>
  event.waitUntil(caches.open(CACHE).then((cache) => cache.add(OFFLINE))),
);
self.addEventListener("activate", (event) =>
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith("trade-offline-") && key !== CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  ),
);
self.addEventListener("fetch", (event) => {
  if (
    event.request.method !== "GET" ||
    new URL(event.request.url).origin !== self.location.origin
  )
    return;
  if (event.request.mode === "navigate")
    event.respondWith(
      fetch(event.request).catch(() =>
        caches.open(CACHE).then((cache) => cache.match(OFFLINE)),
      ),
    );
});
