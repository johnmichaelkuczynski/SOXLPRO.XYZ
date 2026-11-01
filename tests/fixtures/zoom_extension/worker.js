// Test-only extension: chrome.tabs.setZoom changes actual browser layout zoom,
// unlike CSS zoom, deviceScaleFactor, or pinch/pageScaleFactor emulation.
chrome.runtime.onInstalled.addListener(() => {});
