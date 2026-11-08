// The type of a room fills in its name, which stays editable (docs/adr/0045).
// First-party, no library: the name is replaced only while it is empty or still
// the label this script put there.
(function () {
  "use strict";
  var kind = document.getElementById("id_kind");
  var name = document.getElementById("id_name");
  if (!kind || !name) {
    return;
  }
  var OTHER = "other";
  var offered = "";

  function label() {
    var option = kind.options[kind.selectedIndex];
    return option && kind.value && kind.value !== OTHER ? option.text : "";
  }

  kind.addEventListener("change", function () {
    if (name.value === "" || name.value === offered) {
      offered = label();
      name.value = offered;
    }
  });
})();
