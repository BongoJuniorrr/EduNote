import { exportProfiles } from "./export_reports.mjs";

exportProfiles(["technical"]).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
