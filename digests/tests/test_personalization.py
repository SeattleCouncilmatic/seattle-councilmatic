"""Match-query tests for digests/services/personalization.py (#235)."""
from datetime import date, timedelta

from django.test import TestCase

from digests.services import personalization
from digests.tests import fixtures

RECENT = (date.today() - timedelta(days=2)).isoformat()
STALE = (date.today() - timedelta(days=40)).isoformat()
SINCE = date.today() - timedelta(days=8)


def _match(sub):
    return personalization.match_items(sub.preferences, SINCE)


class BillMatchTests(TestCase):
    def test_issue_area_tag_match(self):
        fixtures.bill("CB 100001", action_date=RECENT, tags=["Housing"])
        sub = fixtures.subscriber("tag@example.org", issue_areas=["Housing"])
        items = _match(sub)
        self.assertEqual([i["identifier"] for i in items], ["CB 100001"])
        self.assertEqual(items[0]["reasons"], ["Tagged Housing"])

    def test_no_match_outside_window(self):
        fixtures.bill("CB 100002", action_date=STALE, tags=["Housing"])
        sub = fixtures.subscriber("stale@example.org", issue_areas=["Housing"])
        self.assertEqual(_match(sub), [])

    def test_unmatched_tag_excluded(self):
        fixtures.bill("CB 100003", action_date=RECENT, tags=["Transportation"])
        sub = fixtures.subscriber("other@example.org", issue_areas=["Housing"])
        self.assertEqual(_match(sub), [])

    def test_followed_rep_sponsorship_match(self):
        rep = fixtures.councilmember("Alexis Mercedes Rinck", "Position 8")
        fixtures.bill("CB 100004", action_date=RECENT, sponsors=[rep])
        sub = fixtures.subscriber("rep@example.org", followed_reps=[rep])
        items = _match(sub)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["reasons"], ["Sponsored by Alexis Mercedes Rinck"])

    def test_district_rep_primary_sponsorship_match(self):
        rep = fixtures.councilmember("Joy Hollingsworth", "District 3")
        fixtures.bill("CB 100005", action_date=RECENT, sponsors=[rep])
        sub = fixtures.subscriber(
            "district@example.org", district_obj=fixtures.district("3")
        )
        items = _match(sub)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["reasons"], ["Sponsored by your district's councilmember"]
        )

    def test_district_dimension_ignores_cosponsorship(self):
        rep = fixtures.councilmember("Joy Hollingsworth", "District 3")
        fixtures.bill("CB 100006", action_date=RECENT, sponsors=[rep], primary=False)
        sub = fixtures.subscriber(
            "cosponsor@example.org", district_obj=fixtures.district("3")
        )
        self.assertEqual(_match(sub), [])

    def test_at_large_district_matches_position_seats(self):
        rep = fixtures.councilmember("Alexis Mercedes Rinck", "Position 8")
        fixtures.bill("CB 100007", action_date=RECENT, sponsors=[rep])
        sub = fixtures.subscriber(
            "atlarge@example.org", district_obj=fixtures.district("At Large")
        )
        items = _match(sub)
        self.assertEqual(len(items), 1)

    def test_followed_bill_match(self):
        b = fixtures.bill("CB 100008", action_date=RECENT)
        sub = fixtures.subscriber("follow@example.org", followed_bills=[b])
        items = _match(sub)
        self.assertEqual(items[0]["reasons"], ["You follow this bill"])

    def test_followed_bill_quiet_without_news(self):
        b = fixtures.bill("CB 100009", action_date=STALE)
        sub = fixtures.subscriber("quietfollow@example.org", followed_bills=[b])
        self.assertEqual(_match(sub), [])

    def test_union_merges_reasons_onto_one_item(self):
        rep = fixtures.councilmember("Dan Strauss", "District 6")
        b = fixtures.bill(
            "CB 100010", action_date=RECENT, tags=["Housing"], sponsors=[rep]
        )
        sub = fixtures.subscriber(
            "union@example.org",
            issue_areas=["Housing"],
            followed_reps=[rep],
            followed_bills=[b],
        )
        items = _match(sub)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["reasons"],
            ["You follow this bill", "Tagged Housing", "Sponsored by Dan Strauss"],
        )

    def test_item_carries_summary_and_latest_action(self):
        fixtures.bill(
            "CB 100011",
            action_date=RECENT,
            tags=["Housing"],
            summary="First paragraph.\n\nSecond paragraph.",
        )
        sub = fixtures.subscriber("content@example.org", issue_areas=["Housing"])
        item = _match(sub)[0]
        self.assertEqual(item["summary"], "First paragraph.")
        self.assertEqual(item["latest_action"], "Passed as amended")
        self.assertEqual(item["date"], RECENT)
        self.assertEqual(item["url_path"], "/legislation/cb-100011")
        self.assertIsNone(item["blurb"])


class ShortTitleTests(TestCase):
    """Digest headlines from Seattle's semicolon-chained legal titles."""

    def test_first_semicolon_clause_wins(self):
        self.assertEqual(
            personalization._short_title(
                "An ordinance relating to the City Light Department; "
                "authorizing the General Manager and Chief Executive Officer "
                "to grant an easement over a portion of fee owned property."
            ),
            "An ordinance relating to the City Light Department",
        )

    def test_long_clause_truncates_at_word_boundary(self):
        title = (
            "A resolution regarding next steps after the forensic evaluation "
            "of the King County Regional Homelessness Authority (KCRHA) and "
            "further steps beyond those next steps"
        )
        short = personalization._short_title(title)
        self.assertLessEqual(len(short), personalization.SHORT_TITLE_MAX + 1)
        self.assertTrue(short.endswith("…"))
        # No mid-word cut: everything before the ellipsis is a title prefix.
        self.assertIn(short[:-1], title)
        self.assertTrue(title.startswith(short[:-1].rstrip()))

    def test_short_title_passes_through(self):
        title = "A resolution creating an Arts and Cultural District."
        self.assertEqual(personalization._short_title(title), title)


class MeetingMatchTests(TestCase):
    def test_meeting_of_followed_reps_committee(self):
        rep = fixtures.councilmember("Robert Kettle", "District 7")
        fixtures.committee_membership(rep, fixtures.committee("Public Safety"))
        fixtures.meeting(
            "Public Safety Committee", start_date=RECENT, overview="Recap.\n\nMore."
        )
        sub = fixtures.subscriber("meeting@example.org", followed_reps=[rep])
        items = _match(sub)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "meeting")
        self.assertEqual(items[0]["reasons"], ["Committee meeting of Robert Kettle"])
        self.assertEqual(items[0]["summary"], "Recap.")

    def test_meeting_of_district_reps_committee(self):
        rep = fixtures.councilmember("Joy Hollingsworth", "District 3")
        fixtures.committee_membership(rep, fixtures.committee("Parks"))
        fixtures.meeting("Parks Committee", start_date=RECENT, overview="Recap.")
        sub = fixtures.subscriber(
            "meetdistrict@example.org", district_obj=fixtures.district("3")
        )
        self.assertEqual(len(_match(sub)), 1)

    def test_meeting_without_summary_excluded(self):
        rep = fixtures.councilmember("Robert Kettle", "District 7")
        fixtures.committee_membership(rep, fixtures.committee("Public Safety"))
        fixtures.meeting("Public Safety Committee", start_date=RECENT)
        sub = fixtures.subscriber("nosummary@example.org", followed_reps=[rep])
        self.assertEqual(_match(sub), [])

    def test_unrelated_committee_excluded(self):
        rep = fixtures.councilmember("Robert Kettle", "District 7")
        fixtures.committee_membership(rep, fixtures.committee("Public Safety"))
        fixtures.meeting("Land Use Committee", start_date=RECENT, overview="Recap.")
        sub = fixtures.subscriber("unrelated@example.org", followed_reps=[rep])
        self.assertEqual(_match(sub), [])


class SnapshotTests(TestCase):
    def test_snapshot_and_rehydrate(self):
        fixtures.bill(
            "CB 100012", action_date=RECENT, tags=["Housing"], summary="Sum."
        )
        rep = fixtures.councilmember("Robert Kettle", "District 7")
        fixtures.committee_membership(rep, fixtures.committee("Public Safety"))
        fixtures.meeting(
            "Public Safety Committee", start_date=RECENT, overview="Recap."
        )
        sub = fixtures.subscriber(
            "snap@example.org", issue_areas=["Housing"], followed_reps=[rep]
        )
        items = _match(sub)
        snap = personalization.snapshot(items)
        # The persisted form is ids + reasons only — no content duplication.
        self.assertEqual(
            sorted(snap[0].keys()), ["id", "reasons", "type"]
        )
        rehydrated = personalization.items_from_snapshot(snap)
        self.assertEqual(
            {(i["type"], i["id"]) for i in rehydrated},
            {(i["type"], i["id"]) for i in items},
        )
        by_key = {(i["type"], i["id"]): i for i in rehydrated}
        for original in items:
            hydrated = by_key[(original["type"], original["id"])]
            self.assertEqual(hydrated["reasons"], original["reasons"])
            self.assertEqual(hydrated["summary"], original["summary"])

    def test_vanished_rows_dropped(self):
        b = fixtures.bill("CB 100013", action_date=RECENT, tags=["Housing"])
        sub = fixtures.subscriber("vanish@example.org", issue_areas=["Housing"])
        snap = personalization.snapshot(_match(sub))
        b.delete()
        self.assertEqual(personalization.items_from_snapshot(snap), [])


class WindowTests(TestCase):
    def test_daily_window_uses_last_sent_at(self):
        from django.utils import timezone

        sub = fixtures.subscriber("window@example.org")
        sub.last_sent_at = timezone.now() - timedelta(days=3)
        since = personalization.window_start("daily", sub, timezone.now())
        self.assertEqual(since, (timezone.now() - timedelta(days=3)).date())

    def test_weekly_window_is_eight_days(self):
        from django.utils import timezone

        sub = fixtures.subscriber("window2@example.org")
        since = personalization.window_start("weekly", sub, timezone.now())
        self.assertEqual(since, (timezone.now() - timedelta(days=8)).date())
