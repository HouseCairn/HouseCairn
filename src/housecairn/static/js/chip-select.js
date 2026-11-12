// Choosing several records: a search field, a list of suggestions, one removable chip per
// choice (docs/adr/0063). First-party, no library.
//
// The page ships a native <select multiple> (templates/components/chip_select.html). This
// script hides it and keeps it as the thing the form submits: the values sent are those the
// select would have sent. The suggestions are the options already in the page, filtered here.
// Pattern: ARIA Authoring Practices, "Editable combobox with list autocomplete" with a
// listbox popup; the chips are buttons, each labelled "Remove <name>".
(function () {
  "use strict";

  var MAX_SHOWN = 50;
  var counter = 0;

  function fold(text) {
    return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  function say(text, vars) {
    return text.replace(/\{(\w+)\}/g, function (whole, key) {
      return vars && key in vars ? vars[key] : whole;
    });
  }

  function make(tag, className, attributes) {
    var element = document.createElement(tag);
    if (className) {
      element.className = className;
    }
    Object.keys(attributes || {}).forEach(function (key) {
      element.setAttribute(key, attributes[key]);
    });
    return element;
  }

  function enhance(root) {
    var select = root.querySelector("select");
    if (!select || root.getAttribute("data-ready")) {
      return;
    }
    var text = function (key) {
      return root.getAttribute("data-text-" + key) || "";
    };
    counter += 1;
    var id = select.id || "chip-select-" + counter;
    var listId = id + "-list";
    var label = document.querySelector('label[for="' + id + '"]');

    var entries = Array.prototype.map.call(select.options, function (option) {
      var group = option.parentNode.tagName === "OPTGROUP" ? option.parentNode.label : "";
      return {
        option: option,
        name: option.text,
        group: group,
        full: group ? group + " · " + option.text : option.text,
        search: fold(group + " " + option.text),
      };
    });
    var chosen = entries.filter(function (entry) {
      return entry.option.selected;
    });

    var box = make("div", "chip-select__box");
    var chips = make("ul", "chip-select__chips", { "aria-label": text("selected") });
    var input = make("input", "chip-select__input", {
      type: "text",
      role: "combobox",
      autocomplete: "off",
      autocapitalize: "off",
      spellcheck: "false",
      "aria-autocomplete": "list",
      "aria-haspopup": "listbox",
      "aria-expanded": "false",
      "aria-controls": listId,
      placeholder: text("placeholder"),
    });
    ["aria-describedby", "aria-invalid", "aria-required"].forEach(function (name) {
      if (select.hasAttribute(name)) {
        input.setAttribute(name, select.getAttribute(name));
      }
    });
    var list = make("ul", "chip-select__list", {
      id: listId,
      role: "listbox",
      "aria-label": label ? label.textContent.trim() : "",
    });
    list.hidden = true;
    var status = make("div", "visually-hidden", { role: "status", "aria-live": "polite" });

    // The label and the summary of the errors point at the field by its id: the search field takes it.
    select.id = id + "-native";
    input.id = id;
    select.hidden = true;
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;

    box.appendChild(chips);
    box.appendChild(input);
    root.appendChild(box);
    root.appendChild(list);
    root.appendChild(status);
    root.classList.add("chip-select--on");
    root.setAttribute("data-ready", "1");

    var shown = [];
    var active = -1;

    function announce(message) {
      status.textContent = "";
      window.setTimeout(function () {
        status.textContent = message;
      }, 30);
    }

    function isOpen() {
      return !list.hidden;
    }

    function setActive(index) {
      Array.prototype.forEach.call(list.children, function (item, position) {
        item.classList.toggle("is-active", position === index);
      });
      active = index;
      if (index >= 0 && list.children[index]) {
        input.setAttribute("aria-activedescendant", list.children[index].id);
        list.children[index].scrollIntoView({ block: "nearest" });
      } else {
        input.removeAttribute("aria-activedescendant");
      }
    }

    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      setActive(-1);
    }

    function render(announceCount) {
      var query = fold(input.value.trim());
      var matches = entries.filter(function (entry) {
        return !entry.option.selected && (query === "" || entry.search.indexOf(query) !== -1);
      });
      shown = matches.slice(0, MAX_SHOWN);
      list.textContent = "";
      shown.forEach(function (entry, position) {
        var item = make("li", "chip-select__option", {
          id: listId + "-" + position,
          role: "option",
          "aria-selected": "false",
        });
        item.appendChild(make("span", "chip-select__name")).textContent = entry.name;
        if (entry.group) {
          item.appendChild(make("span", "chip-select__group")).textContent = entry.group;
          item.setAttribute("aria-label", entry.full);
        }
        item.addEventListener("mousedown", function (event) {
          event.preventDefault(); // the focus stays in the search field
        });
        item.addEventListener("click", function () {
          pick(entry);
        });
        list.appendChild(item);
      });
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      setActive(-1);
      if (announceCount) {
        var total = matches.length;
        var message = total === 0 ? text("none") : total === 1 ? text("one") : say(text("many"), { count: total });
        if (total > shown.length) {
          message = say(text("capped"), { count: total, shown: shown.length });
        }
        announce(message);
      }
    }

    function paintChips() {
      chips.textContent = "";
      chosen.forEach(function (entry) {
        var chip = make("li", "chip-select__chip");
        chip.appendChild(make("span", "chip-select__chip-text")).textContent = entry.full;
        var remove = make("button", "chip-select__remove", {
          type: "button",
          "aria-label": say(text("remove"), { name: entry.full }),
        });
        remove.appendChild(make("span", "", { "aria-hidden": "true" })).textContent = "×";
        remove.addEventListener("click", function () {
          unpick(entry, true);
        });
        chip.appendChild(remove);
        chips.appendChild(chip);
      });
    }

    function pick(entry) {
      entry.option.selected = true;
      chosen.push(entry);
      paintChips();
      input.value = "";
      announce(say(text("added"), { name: entry.full }));
      input.focus();
      render(false);
    }

    function unpick(entry, focusAfter) {
      entry.option.selected = false;
      chosen = chosen.filter(function (other) {
        return other !== entry;
      });
      paintChips();
      announce(say(text("removed"), { name: entry.full }));
      if (focusAfter) {
        input.focus();
      }
      if (isOpen()) {
        render(false);
      }
    }

    input.addEventListener("input", function () {
      render(true);
    });

    input.addEventListener("click", function () {
      if (!isOpen()) {
        render(true);
      }
    });

    input.addEventListener("keydown", function (event) {
      var key = event.key;
      if (key === "ArrowDown") {
        event.preventDefault();
        if (!isOpen()) {
          render(true);
        }
        if (shown.length) {
          setActive(active + 1 >= shown.length ? 0 : active + 1);
        }
      } else if (key === "ArrowUp") {
        event.preventDefault();
        if (!isOpen()) {
          render(true);
        }
        if (shown.length) {
          setActive(active <= 0 ? shown.length - 1 : active - 1);
        }
      } else if (key === "Enter") {
        if (isOpen() && active >= 0) {
          event.preventDefault();
          pick(shown[active]);
        } else if (input.value.trim() !== "") {
          event.preventDefault(); // typed text is a search, never a submission
          if (shown.length) {
            pick(shown[0]);
          }
        }
      } else if (key === "Escape") {
        if (isOpen()) {
          event.preventDefault();
          event.stopPropagation();
          close();
        } else if (input.value !== "") {
          event.preventDefault();
          input.value = "";
        }
      } else if (key === "Backspace" && input.value === "" && chosen.length) {
        event.preventDefault();
        unpick(chosen[chosen.length - 1], false);
      }
    });

    root.addEventListener("focusout", function (event) {
      if (!event.relatedTarget || !root.contains(event.relatedTarget)) {
        close();
        input.value = "";
      }
    });

    paintChips();
  }

  function enhanceAll() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-chip-select]"), enhance);
  }

  enhanceAll();
  // A page swapped in place by HTMX (a refused form) brings fresh fields.
  document.addEventListener("htmx:afterSettle", enhanceAll);
})();
