(() => {
  'use strict';

  const original = '/publication/assets/avina-mark.png';
  const shared = '/publication/brand-image';
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

    function load(blob, useShared = false) {
      const request = ++revision;
      let url;
      if (useShared) url = shared + '?v=' + Date.now();
      else if (blob) url = URL.createObjectURL(blob);
      else url = original;
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
          onImage(image, Boolean(blob) || useShared);
          resolve(true);
        };
        image.onerror = () => {
          if (blob) URL.revokeObjectURL(url);
          reject(Error('تصویر لوگو خوانده نشد.'));
        };
        image.src = url;
      });
    }

    load(null, true).catch(async () => {
      if (revision !== 1) return;
      let fallbackRevision = revision;
      if (window.indexedDB) {
        try {
          const blob = await withStore('readonly', store => store.get('logo'));
          if (revision !== 1) return;
          if (blob) {
            fallbackRevision = revision + 1;
            await load(blob);
            return;
          }
        } catch {}
      }
      if (revision === fallbackRevision) await load().catch(() => {});
    });

    async function saveShared(pin) {
      const file = input.files[0];
      if (!file) throw Error('اول فایل لوگو را انتخاب کن.');
      if (!pin) throw Error('PIN پنل مدیریت را وارد کن.');
      if (!accepted.includes(file.type) || file.size > maxSize) {
        throw Error('یک تصویر PNG، JPG یا WebP تا ۸ مگابایت انتخاب کن.');
      }
      // Verify the browser can decode the selected image before replacing the shared file.
      if (!await load(file)) throw Error('انتخاب لوگو تغییر کرد. دوباره تلاش کن.');
      const response = await fetch('/api/publication/brand-image', {
        method: 'PUT',
        headers: {'X-Bot-Pin': pin, 'Content-Type': file.type},
        body: file,
      });
      if (!response.ok) {
        throw Error(response.status === 401 ? 'PIN پنل نادرست است.' : 'ثبت لوگو روی سرور انجام نشد.');
      }
      await load(null, true);
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
    return {saveShared};
  }

  window.AvinaTradeBrand = {bind};
})();
