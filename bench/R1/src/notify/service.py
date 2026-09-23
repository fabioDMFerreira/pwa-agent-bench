"""Fan a templated notification out to a list of users."""

from dataclasses import dataclass, field

from .templates import render


@dataclass
class Summary:
    sent: int = 0
    failed: int = 0
    skipped: list[int] = field(default_factory=list)


class NotificationService:
    def __init__(self, directory, templates, sender):
        self.directory = directory
        self.templates = templates
        self.sender = sender

    @staticmethod
    def _dedupe(user_ids):
        """Drop repeated ids, keeping first-seen order."""
        return list(dict.fromkeys(user_ids))

    def notify(self, user_ids, template_name: str, context: dict) -> Summary:
        """Render `template_name` for every distinct user and deliver it.

        Each user gets the template for their locale when one exists
        (`<name>.<locale>`), else the default template.

        Unknown, inactive and webhook-less users are recorded in
        `Summary.skipped` and never stop the rest of the batch.
        """
        summary = Summary()
        for uid in self._dedupe(user_ids):
            user = self.directory.get(uid)
            if user is None or not user.active:
                summary.skipped.append(uid)
                continue
            if not user.webhook_url:
                summary.skipped.append(uid)
                return summary
            template = self.templates.get_localized(template_name, user.locale)
            text = render(template, {**context, "name": user.name})
            result = self.sender.send(user.webhook_url, {"user": uid, "text": text})
            if result.ok:
                summary.sent += 1
            else:
                summary.failed += 1
        return summary
