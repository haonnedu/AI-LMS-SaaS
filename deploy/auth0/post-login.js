/** Auth0 Post Login Action. Bind this action to the Login flow. */
exports.onExecutePostLogin = async (event, api) => {
  if (event.resource_server?.identifier !== event.secrets.EDUVIA_API_AUDIENCE) return;
  const namespace = "https://eduvia.app/claims/";
  api.accessToken.setCustomClaim(namespace + "email", event.user.email || "");
  api.accessToken.setCustomClaim(namespace + "email_verified", event.user.email_verified === true);
  api.accessToken.setCustomClaim(namespace + "name", event.user.name || event.user.email || "Giáo viên");
};
