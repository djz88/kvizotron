async (page) => {
  // For browser_run_code_unsafe. Copy to .playwright-mcp/, fill in the three constants, add steps.
  const BASE = "https://localhost:18443";
  const ADMIN_STATE = "<absolute path to the saved login state>";
  const SHOTS = "<absolute path to a scratchpad folder>";

  const browser = page.context().browser();
  const log = {};
  const errs = [];
  const VIEWS = {
    main: { locale: "cs", colorScheme: "light", viewport: { width: 1280, height: 900 } },
    phone: { locale: "uk", colorScheme: "dark", viewport: { width: 390, height: 844 } },
  };

  const contexts = [];
  const open = async (name, view, storageState) => {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      timezoneId: "Europe/Prague",
      storageState,
      ...view,
    });
    contexts.push(context);
    const tab = await context.newPage();
    tab.setDefaultTimeout(30000);
    tab.on("pageerror", (error) => errs.push(`${name}: ${error}`));
    tab.on("console", (message) => {
      if (message.type() === "error") errs.push(`${name}: ${message.text()} ${message.location().url}`);
    });
    return tab;
  };
  const shot = (tab, name) => tab.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
  const main = async (tab) =>
    (await tab.textContent("main")).replace(/\s+/g, " ").trim().slice(0, 300);

  try {
    // The participant has no login, so this view also shows whether the stack answers.
    const visitor = await open("visitor", VIEWS.phone);
    await visitor.goto(`${BASE}/?lang=uk`);
    log.visitor = await main(visitor);
    await shot(visitor, "visitor-phone");

    const admin = await open("admin", VIEWS.main, ADMIN_STATE);
    await admin.goto(`${BASE}/admin/settings?lang=cs`);
    log.adminUrl = admin.url();
    if (admin.url().includes("login")) log.stopped = "the saved login expired";
    else {
      await shot(admin, "admin-settings");
      // Steps of this walkthrough go here.
    }
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
  return { ...log, errs };
}
