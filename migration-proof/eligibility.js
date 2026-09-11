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
    if (typeof value === "number") {
      if (!Number.isSafeInteger(value)) return NaN;
      return value;
    }
    if (typeof value === "string") {
      var trimmed = value.trim();
      if (!/^(?:0|[1-9]\d*)$/.test(trimmed)) return NaN;
      var parsed = Number(trimmed);
      if (!Number.isSafeInteger(parsed) || String(parsed) !== trimmed) return NaN;
      return parsed;
    }
    return NaN;
  }

  function classify(input) {
    if (typeof input !== "object" || input === null || Array.isArray(input)) {
      return { status: "incomplete" };
    }
    var src = input;
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
      !Number.isSafeInteger(objectCount) ||
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
