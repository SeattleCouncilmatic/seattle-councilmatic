from django.apps import AppConfig


class SeattleCouncilmaticConfig(AppConfig):
    name = "seattle_app"
    verbose_name = "Seattle Councilmatic"

    def ready(self):
        import councilmatic_core.signals.handlers