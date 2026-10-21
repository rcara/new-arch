/* New Arch — amélioration progressive. Tout fonctionne sans ce fichier :
   menus <details>, panneaux :target et formulaire de dépôt restent natifs.
   Aucun état local, aucun appel réseau : les envois passent par les
   formulaires existants (CSRF, foyer actif et permissions côté serveur). */
(function () {
  "use strict";

  var MENUS = "details.menu, details.foyer-switcher";
  var FOCUSABLE = "a[href], button:not([disabled]), input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

  function closeMenus(except) {
    document.querySelectorAll(MENUS).forEach(function (menu) {
      if (menu.open && menu !== except && !(except && menu.contains(except))) {
        menu.open = false;
      }
    });
  }

  function focusables(root) {
    return Array.prototype.filter.call(root.querySelectorAll(FOCUSABLE), function (el) {
      return el.offsetParent !== null || el === document.activeElement;
    });
  }

  /* Menus : un seul ouvert, fermeture au clic extérieur et à Échap. */
  document.addEventListener("toggle", function (event) {
    var menu = event.target;
    if (menu.open && menu.matches && menu.matches(MENUS)) {
      closeMenus(menu);
    }
  }, true);

  document.addEventListener("click", function (event) {
    var inside = event.target.closest && event.target.closest(MENUS);
    closeMenus(inside || null);
  });

  /* Panneaux d'ajout rapide (#ajout-tache, #ajout-evenement). */
  var opener = null;
  var scroll = null;

  function openPanel() {
    var id = location.hash.slice(1);
    var panel = id && document.getElementById(id);
    return panel && panel.classList.contains("quick-panel") ? panel : null;
  }

  function onPanelChange() {
    var panel = openPanel();
    if (panel) {
      closeMenus(null);
      var first = panel.querySelector("form " + FOCUSABLE) || focusables(panel)[0];
      if (first) {
        first.focus({ preventScroll: true });
      }
      return;
    }
    if (scroll) {
      window.scrollTo(scroll[0], scroll[1]);
      scroll = null;
    }
    if (opener && document.contains(opener)) {
      opener.focus({ preventScroll: true });
    }
    opener = null;
  }

  function closePanel() {
    scroll = [window.scrollX, window.scrollY];
    location.hash = "contenu";
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest("a[href^='#']");
    if (!link) {
      return;
    }
    var target = document.getElementById(link.getAttribute("href").slice(1));
    if (target && target.classList.contains("quick-panel")) {
      var menu = link.closest(MENUS);
      opener = menu ? menu.querySelector("summary") : link;
      scroll = [window.scrollX, window.scrollY];
      return;
    }
    if (openPanel() && (link.classList.contains("quick-close") || link.classList.contains("quick-backdrop"))) {
      event.preventDefault();
      closePanel();
    }
  });

  window.addEventListener("hashchange", function () {
    onPanelChange();
    if (scroll && openPanel()) {
      window.scrollTo(scroll[0], scroll[1]);
    }
  });

  document.addEventListener("keydown", function (event) {
    var panel = openPanel();
    if (event.key === "Escape" || event.key === "Esc") {
      if (panel) {
        event.preventDefault();
        closePanel();
        return;
      }
      var menus = Array.prototype.filter.call(document.querySelectorAll("details[open]"), function (d) {
        return d.closest(MENUS);
      });
      if (!menus.length) {
        return;
      }
      var active = document.activeElement;
      var inner = menus.filter(function (d) { return d.contains(active); }).pop() || menus[0];
      inner.open = false;
      var summary = inner.querySelector("summary");
      if (summary) {
        summary.focus();
      }
      event.preventDefault();
      return;
    }
    if (event.key === "Tab" && panel) {
      var items = focusables(panel);
      if (!items.length) {
        return;
      }
      var first = items[0];
      var last = items[items.length - 1];
      if (!panel.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  document.addEventListener("focusin", function (event) {
    var panel = openPanel();
    if (panel && !panel.contains(event.target)) {
      var items = focusables(panel);
      if (items.length) {
        items[0].focus({ preventScroll: true });
      }
    }
  });

  if (openPanel()) {
    onPanelChange();
  }

  /* Coffre : glisser-déposer sur toute la zone, envoi par le formulaire existant. */
  document.querySelectorAll(".drop-zone").forEach(function (zone) {
    var input = zone.querySelector("input[type=file]");
    var form = zone.closest("form");
    var title = zone.querySelector(".drop-title");
    if (!input || !form || typeof DataTransfer === "undefined") {
      return;
    }
    var depth = 0;

    function hasFiles(event) {
      var types = event.dataTransfer && event.dataTransfer.types;
      return types && Array.prototype.indexOf.call(types, "Files") !== -1;
    }

    function showName() {
      if (title && input.files.length) {
        title.textContent = input.files[0].name;
      }
    }

    zone.addEventListener("dragenter", function (event) {
      if (!hasFiles(event)) {
        return;
      }
      event.preventDefault();
      depth += 1;
      zone.classList.add("is-dragover");
    });
    zone.addEventListener("dragover", function (event) {
      if (hasFiles(event)) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }
    });
    zone.addEventListener("dragleave", function () {
      depth = Math.max(0, depth - 1);
      if (!depth) {
        zone.classList.remove("is-dragover");
      }
    });
    zone.addEventListener("drop", function (event) {
      if (!hasFiles(event)) {
        return;
      }
      event.preventDefault();
      depth = 0;
      zone.classList.remove("is-dragover");
      var dropped = event.dataTransfer.files;
      if (!dropped.length) {
        return;
      }
      var transfer = new DataTransfer();
      transfer.items.add(dropped[0]);
      input.files = transfer.files;
      showName();
      if (form.checkValidity()) {
        var submit = form.querySelector("button[type=submit][name=confirm]");
        if (form.requestSubmit) {
          form.requestSubmit(submit || undefined);
        } else if (submit) {
          submit.click();
        }
      } else {
        form.reportValidity();
      }
    });
    input.addEventListener("change", showName);

    window.addEventListener("dragover", function (event) {
      if (hasFiles(event) && !zone.contains(event.target)) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "none";
      }
    });
    window.addEventListener("drop", function (event) {
      if (hasFiles(event) && !zone.contains(event.target)) {
        event.preventDefault();
      }
    });
  });
}());
