"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const addButton = document.getElementById("add-break");
  const container = document.getElementById("break-forms");
  const template = document.getElementById("empty-break-template");
  const totalForms = document.getElementById("id_breaks-TOTAL_FORMS");

  if (!addButton || !container || !template || !totalForms) {
    return;
  }

  const maxForms = 20;

  addButton.addEventListener("click", () => {
    const current = Number(totalForms.value);

    if (!Number.isInteger(current) || current >= maxForms) {
      return;
    }

    const html = template.innerHTML.replaceAll("__prefix__", String(current));

    container.insertAdjacentHTML("beforeend", html);

    totalForms.value = String(current + 1);

    const added = container.lastElementChild;
    const firstInput = added?.querySelector('input[type="datetime-local"]');

    firstInput?.focus();

    if (current + 1 >= maxForms) {
      addButton.disabled = true;
    }
  });
});
