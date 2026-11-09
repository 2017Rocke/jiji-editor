// Loaded only by the explicit --verify-native mode. Exercise real UI handlers in WebView2.
window.jijiNativeTest = (() => {
  let sizes, revision;
  const dimensions = () => state.pages.map(page => [page.width, page.height]);
  return {
    beginCrop() {
      sizes = dimensions();
      revision = state.revision;
      document.querySelector('.tool[data-tool="crop"]').click();
      document.querySelector('.thumb[data-page="2"] input').click();
      document.querySelector('.thumb[data-page="1"]').click();
      if (selected.size !== 2 || !selected.has(0) || !selected.has(2)) throw new Error('Page selection failed');
      document.querySelector('[data-crop="0.1"]').click();
      document.getElementById('applyBtn').click();
    },
    cropped() {
      if (state.revision <= revision || state.pages.length !== 3) return false;
      return dimensions().every((size, page) => size.every((value, axis) =>
        Math.abs(value - sizes[page][axis] * (page === 1 ? 1 : 0.8)) < 0.11));
    },
    restored() {
      return state.revision >= revision + 2 && JSON.stringify(dimensions()) === JSON.stringify(sizes);
    },
    changedAfterClose() { return state.revision >= revision + 4; }
  };
})();
