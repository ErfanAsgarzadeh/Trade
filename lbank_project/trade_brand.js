(() => {
  'use strict';

  const original = '/publication/assets/avina-mark.png';
  const maxSize = 8 * 1024 * 1024;
  const accepted = ['image/png', 'image/jpeg', 'image/webp'];

  function withStore(mode, operation) {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open('avina-publication-brand', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('images');
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result;
        const tx = db.transaction('images', mode);
        const result = operation(tx.objectStore('images'));
        tx.oncomplete = () => { db.close(); resolve(result.result); };
        tx.onabort = tx.onerror = () => { db.close(); reject(tx.error); };
      };
    });
  }

  function bind(input, preview, onImage, onMessage) {
    let activeUrl;
    let revision = 0;

    function load(blob) {
      const request = ++revision;
      const url = blob ? URL.createObjectURL(blob) : original;
      return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => {
          if (request !== revision) {
            if (blob) URL.revokeObjectURL(url);
            resolve(false);
            return;
          }
          if (activeUrl) URL.revokeObjectURL(activeUrl);
          activeUrl = blob ? url : null;
          preview.src = url;
          onImage(image, Boolean(blob));
          resolve(true);
        };
        image.onerror = () => {
          if (blob) URL.revokeObjectURL(url);
          reject(Error('تصویر لوگو خوانده نشد.'));
        };
        image.src = url;
      });
    }

    load().catch(() => {});
    if (window.indexedDB) {
      withStore('readonly', store => store.get('logo'))
        .then(blob => { if (blob && revision === 1) return load(blob); })
        .catch(() => {});
    }

    input.onchange = async () => {
      const file = input.files[0];
      if (!file) return;
      if (!accepted.includes(file.type) || file.size > maxSize) {
        onMessage('یک تصویر PNG، JPG یا WebP تا ۸ مگابایت انتخاب کن.');
        return;
      }
      try {
        if (!await load(file)) return;
        if (window.indexedDB) {
          try {
            await withStore('readwrite', store => store.put(file, 'logo'));
            onMessage('لوگو در همین مرورگر ذخیره شد.');
            return;
          } catch {}
        }
        onMessage('لوگو برای این صفحه فعال شد.');
      } catch (error) { onMessage(error.message); }
    };
  }

  window.AvinaTradeBrand = {bind};
})();
