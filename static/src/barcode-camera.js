import { BrowserMultiFormatReader } from "@zxing/browser";

const readers = new WeakMap();

function stop(root) {
  const reader = readers.get(root);
  if (reader) {
    reader.controls.stop();
    readers.delete(root);
  }
  const video = root.querySelector("video");
  if (video) video.srcObject = null;
  root.dispatchEvent(new CustomEvent("smartmart:camera-stopped"));
}

async function start(root) {
  stop(root);
  const status = root.querySelector("[data-camera-status]");
  const video = root.querySelector("video");
  const select = root.querySelector("[data-camera-select]");
  const requestedDeviceId = select.value;
  const reader = new BrowserMultiFormatReader();
  try {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("Camera scanning requires a supported browser and HTTPS (or localhost).");
    }
    status.textContent = "Requesting camera permission…";
    const devices = await BrowserMultiFormatReader.listVideoInputDevices();
    if (!devices.length) throw new Error("No camera was found on this device.");
    select.replaceChildren();
    devices.forEach((device, index) => select.add(new Option(device.label || `Camera ${index + 1}`, device.deviceId)));
    select.hidden = devices.length < 2;
    const deviceId = devices.some((device) => device.deviceId === requestedDeviceId)
      ? requestedDeviceId : devices[0].deviceId;
    const controls = await reader.decodeFromVideoDevice(deviceId, video, (result) => {
      root.dispatchEvent(new CustomEvent("smartmart:camera-frame", { detail: { barcode: result ? result.getText() : "" } }));
    });
    readers.set(root, { reader, controls });
    status.textContent = "Camera is running. Hold a barcode in the frame.";
  } catch (error) {
    stop(root);
    status.textContent = error && error.name === "NotAllowedError"
      ? "Camera permission was denied. Allow camera access or use the scanner input."
      : (error.message || "Could not start the camera. Use the scanner input instead.");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-barcode-camera]").forEach((root) => {
    let lastText = "", resetTimer = null;
    root.querySelector("[data-camera-start]").addEventListener("click", () => start(root));
    root.querySelector("[data-camera-stop]").addEventListener("click", () => stop(root));
    root.querySelector("[data-camera-select]").addEventListener("change", () => start(root));
    root.addEventListener("smartmart:camera-frame", (event) => {
      const text = event.detail.barcode;
      if (text) {
        clearTimeout(resetTimer);
        resetTimer = null;
        if (text !== lastText) root.dispatchEvent(new CustomEvent("smartmart:barcode", { detail: { barcode: text } }));
        lastText = text;
      } else {
        clearTimeout(resetTimer);
        resetTimer = setTimeout(() => { lastText = ""; }, 800);
      }
    });
    root.addEventListener("smartmart:camera-stopped", () => { clearTimeout(resetTimer); lastText = ""; });
  });
});

export { start, stop };
