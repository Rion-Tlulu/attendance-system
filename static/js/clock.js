"use strict";

document.addEventListener("DOMContentLoaded", () => {
  // 日付と時刻は表示用。打刻時刻はDjangoサーバーで決定する。
  const dateElement = document.getElementById("current-date");
  const clockElement = document.getElementById("current-clock");
  const dateFormatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  });
  const timeFormatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  const renderClock = () => {
    const now = new Date();
    if (dateElement) dateElement.textContent = dateFormatter.format(now);
    if (clockElement) clockElement.textContent = timeFormatter.format(now);
  };
  renderClock();
  if (dateElement || clockElement) window.setInterval(renderClock, 1000);

  let submitting = false;
  const forms = [...document.querySelectorAll(".clock-form")];
  forms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (submitting) {
        event.preventDefault();
        return;
      }
      submitting = true;
      // 同じページの他の打刻操作も押せないようにする。
      forms.forEach((otherForm) => {
        const button = otherForm.querySelector('button[type="submit"]');
        if (!button) return;
        button.disabled = true;
        if (otherForm === form) {
          button.textContent = "記録中…";
        }
      });
    });
  });

  // ブラウザの戻る操作等で無効状態が残った際は画面を再取得する。
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });
});
