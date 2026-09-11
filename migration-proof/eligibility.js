(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof root === "object" && root !== null) {
    root.classify = api.classify;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function present(value) {
    return value !== undefined && value !== null && String(value).trim() !== "";
  }

  function asBool(value) {
    if (value === true || value === false) return value;
    return null;
  }

  function asPositiveInt(value) {
    if (typeof value === "number" && Number.isInteger(value)) return value;
    if (typeof value === "string" && /^(?:0|[1-9]\d*)$/.test(value.trim())) {
      return parseInt(value.trim(), 10);
    }
    return NaN;
  }

  function classify(input) {
    var src = input || {};
    var engine = src.engine;
    var target = src.target;
    var authorized = asBool(src.authorized);
    var reportingOnly = asBool(src.reportingOnly);
    var privateData = asBool(src.privateData);
    var objectCount = asPositiveInt(src.objectCount);

    if (
      !present(engine) ||
      !present(target) ||
      authorized === null ||
      reportingOnly === null ||
      privateData === null ||
      !Number.isInteger(objectCount) ||
      objectCount <= 0
    ) {
      return { status: "incomplete" };
    }

    if (
      engine !== "sqlserver" ||
      target !== "postgresql" ||
      authorized !== true ||
      reportingOnly !== true
    ) {
      return { status: "unsupported" };
    }

    if (privateData === true) {
      return { status: "private-review" };
    }

    return { status: "review" };
  }

  return { classify: classify };
});
