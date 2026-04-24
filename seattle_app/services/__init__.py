# Submodules (claude_service, municode_client) are imported on demand to
# avoid pulling in optional dependencies (like anthropic) at package load
# time. Callers should import from the submodule directly:
#     from seattle_app.services import municode_client
#     from seattle_app.services.claude_service import ClaudeService
