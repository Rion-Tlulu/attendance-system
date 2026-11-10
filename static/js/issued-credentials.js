"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const input = document.querySelector("[data-issued-password]");
  const toggle = document.querySelector("[data-issued-toggle]");
  const copy = document.querySelector("[data-issued-copy]");
  const result = document.querySelector("[data-issued-result]");
  if (!input || !toggle || !copy || !result) return;

  toggle.addEventListener("click", () => {
    const visible = input.type === "password";
    input.type = visible ? "text" : "password";
    toggle.textContent = visible ? "隠す" : "表示する";
    toggle.setAttribute("aria-pressed", String(visible));
  });

  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(input.value);
      result.textContent = "初期パスワードをコピーしました。";
    } catch (_) {
      input.type = "text";
      toggle.textContent = "隠す";
      toggle.setAttribute("aria-pressed", "true");
      input.focus();
      input.select();
      result.textContent = "コピーできませんでした。表示された文字列を手動でコピーしてください。";
    }
  });
});
