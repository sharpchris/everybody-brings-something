// Site-wide behavior, loaded deferred on every page.

// htmx ignores error responses by default; tell the person what happened instead of doing nothing.
(function () {
  const box = document.getElementById("request-error");
  if (!box) return;
  const messages = {
    403: "You can only change your own signups.",
    404: "That's no longer available. Reload the page to see the latest sheet.",
  };
  document.addEventListener("htmx:responseError", (e) => {
    box.textContent = messages[e.detail.xhr.status] || "That didn't save. Reload the page and try again.";
    box.hidden = false;
    box.scrollIntoView({ block: "nearest" });
  });
  document.addEventListener("htmx:sendError", () => {
    box.textContent = "Couldn't reach the server. Check your connection and try again.";
    box.hidden = false;
  });
  document.addEventListener("htmx:afterRequest", (e) => {
    if (e.detail.successful) box.hidden = true;
  });
})();

// Share link field: follow the title (slugified like Django's slugify) until it's touched by hand.
(function () {
  function slugify(value) {
    return value
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^\x00-\x7F]/g, "")
      .toLowerCase()
      .replace(/[^\w\s-]/g, "")
      .replace(/[-\s]+/g, "-")
      .replace(/^[-_]+|[-_]+$/g, "")
      .slice(0, 70)
      .replace(/-+$/, "");
  }

  // A short random ending makes links hard to guess (picnic-k3f9). Same alphabet as services.SLUG_SUFFIX_ALPHABET.
  const alphabet = "abcdefghjkmnpqrstuvwxyz23456789";
  const suffix = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => alphabet[b % alphabet.length]).join("");
  const autoSlug = (title) => {
    const base = slugify(title);
    return base ? `${base}-${suffix}` : "";
  };

  document.querySelectorAll("[data-slug-target]").forEach((slug) => {
    const form = slug.form;
    const title = form && form.querySelector("[data-slug-source]");
    const auto = form && form.querySelector('input[name="slug_auto"]');
    if (!title || !auto || slug.hasAttribute("data-slug-locked")) return;

    // Once the field is touched by hand it's never auto-filled again. After a validation
    // error the page is re-rendered, so carry that state over from the submitted form.
    let manual = slug.value !== "" && auto.value !== "True";
    const sync = () => {
      auto.value = manual ? "" : "True";
      if (!manual) slug.value = autoSlug(title.value);
    };

    title.addEventListener("input", sync);
    slug.addEventListener("input", () => {
      manual = true;
      auto.value = "";
    }, { once: true });
    if (!manual) sync();
  });
})();

// "Copy share link" (admin): copies the event's full address, built from the address the admin is
// using so it's right behind a proxy or on a custom domain.
(function () {
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    // Plain-HTTP sites (e.g. on a home network) can't use the clipboard API.
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const ok = document.execCommand("copy");
    field.remove();
    return ok ? Promise.resolve() : Promise.reject(new Error("copy failed"));
  }

  document.addEventListener("click", (e) => {
    const button = e.target.closest("[data-copy-path]");
    if (!button) return;
    const url = new URL(button.dataset.copyPath, window.location.origin).href;
    copyText(url)
      .then(() => { button.classList.add("copied"); })
      .catch(() => { window.prompt("Copy this link:", url); })
      .finally(() => {
        clearTimeout(button._reset);
        button._reset = setTimeout(() => { button.classList.remove("copied"); }, 2000);
      });
  });
})();

// New-event page: "+ Add another field" copies a blank custom field row; the trash icon removes one.
// After a removal the remaining rows are renumbered so Django's formset sees them as 0..n-1.
(function () {
  function renumber(box) {
    const rows = box.querySelectorAll("[data-field-rows] > .field-row");
    rows.forEach((row, i) => {
      row.querySelectorAll("[name], [id], [for]").forEach((el) => {
        for (const attr of ["name", "id", "for"]) {
          const value = el.getAttribute(attr);
          if (value) el.setAttribute(attr, value.replace(/fields-\d+-/, `fields-${i}-`));
        }
      });
    });
    box.querySelector('input[name$="-TOTAL_FORMS"]').value = String(rows.length);
  }

  document.addEventListener("click", (e) => {
    const remove = e.target.closest("[data-remove-field-row]");
    if (remove) {
      const box = remove.closest("details");
      remove.closest(".field-row").remove();
      renumber(box);
      return;
    }
    const button = e.target.closest("[data-add-field-row]");
    if (!button) return;
    const box = button.closest("details");
    const rows = box.querySelector("[data-field-rows]");
    const template = box.querySelector("[data-field-row-template]");
    const total = box.querySelector('input[name$="-TOTAL_FORMS"]');
    const index = Number(total.value);
    rows.insertAdjacentHTML("beforeend", template.innerHTML.replace(/__prefix__/g, String(index)));
    total.value = String(index + 1);
    rows.lastElementChild.querySelector("input:not([type=hidden])")?.focus();
  });
})();
