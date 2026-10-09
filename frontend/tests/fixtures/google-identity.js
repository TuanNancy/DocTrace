// Loaded only by Playwright's network interception; no real Google requests.
(() => {
  let config;
  window.google = {
    accounts: {
      id: {
        initialize(options) { config = options; },
        renderButton(container) {
          const options = config;
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = "Tiếp tục với Google";
          button.dataset.clientId = options.client_id;
          button.dataset.nonce = options.nonce;
          button.dataset.uxMode = options.ux_mode;
          button.addEventListener("click", () => options.callback({
            credential: `fixture-google:${options.nonce}`,
            client_id: options.client_id,
            select_by: "btn",
          }));
          container.replaceChildren(button);
        },
        cancel() {},
      },
    },
  };
})();
