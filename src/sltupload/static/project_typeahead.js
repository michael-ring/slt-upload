(() => {
  const root = document.querySelector("[data-project-typeahead]");
  const input = root?.querySelector("#project-input");
  const list = root?.querySelector("#project-suggestions");

  if (!(root instanceof HTMLElement) || !(input instanceof HTMLInputElement) || !(list instanceof HTMLElement)) {
    return;
  }

  const suggestions = Array.from(list.querySelectorAll("[data-project-option]")).map((element) => ({
    element,
    value: element.getAttribute("data-value") ?? element.textContent?.trim() ?? "",
  }));
  let activeSuggestion = null;

  const visibleSuggestions = () => suggestions.filter((suggestion) => !suggestion.element.hidden);

  const setActiveSuggestion = (suggestion) => {
    activeSuggestion = suggestion;
    suggestions.forEach((item) => {
      const isActive = item === suggestion;
      item.element.classList.toggle("is-active", isActive);
      item.element.setAttribute("aria-selected", String(isActive));
    });
    if (suggestion) {
      input.setAttribute("aria-activedescendant", suggestion.element.id);
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  };

  const closeSuggestions = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    setActiveSuggestion(null);
  };

  const openSuggestions = () => {
    if (visibleSuggestions().length === 0) {
      closeSuggestions();
      return;
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };

  const filterSuggestions = () => {
    const query = input.value.trim().toLocaleLowerCase();
    suggestions.forEach((suggestion) => {
      suggestion.element.hidden = Boolean(query) && !suggestion.value.toLocaleLowerCase().includes(query);
    });
    setActiveSuggestion(null);
    if (document.activeElement === input) {
      openSuggestions();
    }
  };

  const chooseSuggestion = (suggestion) => {
    input.value = suggestion.value;
    closeSuggestions();
  };

  input.addEventListener("focus", filterSuggestions);
  input.addEventListener("input", filterSuggestions);
  input.addEventListener("keydown", (event) => {
    const visible = visibleSuggestions();
    if ((event.key === "ArrowDown" || event.key === "ArrowUp") && visible.length > 0) {
      event.preventDefault();
      const currentIndex = activeSuggestion ? visible.indexOf(activeSuggestion) : -1;
      const offset = event.key === "ArrowDown" ? 1 : -1;
      const nextIndex = (currentIndex + offset + visible.length) % visible.length;
      setActiveSuggestion(visible[nextIndex]);
      openSuggestions();
    } else if (event.key === "Enter" && activeSuggestion) {
      event.preventDefault();
      chooseSuggestion(activeSuggestion);
    } else if (event.key === "Escape" && !list.hidden) {
      event.preventDefault();
      closeSuggestions();
    }
  });

  input.addEventListener("blur", () => {
    window.setTimeout(() => {
      if (!root.contains(document.activeElement)) {
        closeSuggestions();
      }
    }, 0);
  });

  suggestions.forEach((suggestion) => {
    const chooseFromPointer = (event) => {
      event.preventDefault();
      chooseSuggestion(suggestion);
    };
    suggestion.element.addEventListener("pointerdown", chooseFromPointer);
    suggestion.element.addEventListener("touchstart", chooseFromPointer, { passive: false });
    suggestion.element.addEventListener("click", chooseFromPointer);
  });

  document.addEventListener("click", (event) => {
    if (event.target instanceof Node && !root.contains(event.target)) {
      closeSuggestions();
    }
  });
})();
