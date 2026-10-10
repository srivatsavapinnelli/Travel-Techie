/* Runs BEFORE the page paints (it is a small blocking script in <head>) so the saved theme is
   applied immediately and there is no flash of the wrong colours. Logic lives in theme.js. */
(function () {
  try {
    var saved = localStorage.getItem('tt_theme');            // 'light' | 'dark' | 'system' | null
    var dark = saved === 'dark' || ((!saved || saved === 'system') && window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  } catch (e) { document.documentElement.setAttribute('data-theme', 'light'); }
})();
