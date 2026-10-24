"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const toggleButtons = document.querySelectorAll("[data-toggle-password]");

  toggleButtons.forEach((button) => {
    const inputId = button.dataset.togglePassword;
    const input = document.getElementById(inputId);

    if (!input) {
      return;
    }

    button.addEventListener("click", () => {
      const isVisible = input.type === "text";

      input.type = isVisible ? "password" : "text";

      button.textContent = isVisible ? "表示" : "非表示";

      button.setAttribute("aria-pressed", String(!isVisible));
    });
  });
});
