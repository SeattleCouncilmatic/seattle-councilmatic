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

    def test_district_rep_sponsorship_match_named_reason(self):
        rep = fixtures.councilmember("Joy Hollingsworth", "District 3")
        fixtures.bill("CB 100005", action_date=RECENT, sponsors=[rep])
        sub = fixtures.subscriber(
            "district@example.org", district_obj=fixtures.district("3")
        )
        items = _match(sub)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["reasons"],
            ["Sponsored by Joy Hollingsworth, your district's councilmember"],
        )

    def test_district_dimension_includes_cosponsorship(self):
        # The district maps to "your representatives" — their co-sponsored
        # work counts as district news too.
        rep = fixtures.councilmember("Joy Hollingsworth", "District 3")
        fixtures.bill("CB 100006", action_date=RECENT, sponsors=[rep], primary=False)
        sub = fixtures.subscriber(
            "cosponsor@example.org", district_obj=fixtures.district("3")
        )
        self.assertEqual(len(_match(sub)), 1)

    def test_district_includes_citywide_members(self):
        # A geographic district's representative set is the district seat
        # PLUS the citywide Position members — mirroring the council map.
        fixtures.councilmember("Joy Hollingsworth", "District 3")
        citywide = fixtures.councilmember("Alexis Mercedes Rinck", "Position 8")
        fixtures.bill("CB 100016", action_date=RECENT, sponsors=[citywide])
        sub = fixtures.subscriber(
            "citywide@example.org", district_obj=fixtures.district("3")
        )
        items = _match(sub)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["reasons"],
            ["Sponsored by Alexis Mercedes Rinck (citywide)"],
        )

    def test_followed_rep_who_is_also_district_rep_gets_one_reason(self):
        rep = fixtures.councilmember("Joy Hollingsworth", "District 3")
        fixtures.bill("CB 100017", action_date=RECENT, sponsors=[rep])
        sub = fixtures.subscriber(
            "both@example.org",
            followed_reps=[rep],
            district_obj=fixtures.district("3"),
        )
        items = _match(sub)
        self.assertEqual(
            items[0]["reasons"],
            ["Sponsored by Joy Hollingsworth, your district's councilmember"],
        )

    def test_at_large_district_matches_position_seats(self):
        rep = fixtures.councilmember("Alexis Mercedes Rinck", "Position 8")
        fixtures.bill("CB 100007", action_date=RECENT, sponsors=[rep])
        sub = fixtures.subscriber(
            "atlarge@example.org", district_obj=fixtures.district("At Large")
        )
        items = _match(sub)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["reasons"],
            ["Sponsored by Alexis Mercedes Rinck (citywide)"],
        )

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


class TagPillTests(TestCase):
    def test_tags_split_matched_from_unmatched(self):
        fixtures.bill(
            "CB 100014",
            action_date=RECENT,
            tags=["Housing", "Transportation"],
        )
        sub = fixtures.subscriber(
            "pillsplit@example.org", issue_areas=["Housing"]
        )
        item = _match(sub)[0]
        self.assertEqual(
            item["tags"],
            [
                {"name": "Housing", "matched": True},
                {"name": "Transportation", "matched": False},
            ],
        )
        # The tag match moved into the pills; no sentence reason remains.
        self.assertEqual(item["display_reasons"], [])
        self.assertEqual(item["reasons"], ["Tagged Housing"])

    def test_non_tag_reasons_stay_sentence_pills(self):
        rep = fixtures.councilmember("Dan Strauss", "District 6")
        fixtures.bill(
            "CB 100015", action_date=RECENT, tags=["Parks"], sponsors=[rep]
        )
        sub = fixtures.subscriber(
            "pillsponsor@example.org", followed_reps=[rep]
        )
        item = _match(sub)[0]
        self.assertEqual(item["display_reasons"], ["Sponsored by Dan Strauss"])
        # Unmatched bill tags still show as (gray) topic pills.
        self.assertEqual(
            item["tags"], [{"name": "Parks", "matched": False}]
        )


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

    def test_subtitle_is_second_clause_only(self):
        title = (
            "An ordinance relating to the City Light Department; "
            "authorizing the General Manager and Chief Executive Officer "
            "or designee to grant an easement to King County; "
            "ratifying and confirming certain prior acts."
        )
        self.assertEqual(
            personalization._title_subtitle(title),
            "authorizing the General Manager and Chief Executive Officer "
            "or designee to grant an easement to King County",
        )

    def test_subtitle_empty_without_semicolon(self):
        self.assertEqual(
            personalization._title_subtitle("A resolution creating a district."),
            "",
        )

    def test_long_subtitle_truncates_at_word_boundary(self):
        title = "Header; " + " ".join(["authorizing"] * 40)
        subtitle = personalization._title_subtitle(title)
        self.assertLessEqual(len(subtitle), personalization.SUBTITLE_MAX + 1)
        self.assertTrue(subtitle.endswith("…"))


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

    def test_full_city_council_meeting_included_for_everyone(self):
        # The full council matches every subscriber — no committee
        # membership (or even a district) required.
        fixtures.meeting("City Council", start_date=RECENT, overview="Recap.")
        sub = fixtures.subscriber("council@example.org", issue_areas=["Housing"])
        meetings = [i for i in _match(sub) if i["type"] == "meeting"]
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0]["reasons"], ["Full City Council meeting"])

    def test_city_council_without_summary_still_excluded(self):
        # "Everyone" doesn't override the needs-a-recap rule.
        fixtures.meeting("City Council", start_date=RECENT)
        sub = fixtures.subscriber("nocouncil@example.org", issue_areas=["Housing"])
        self.assertEqual(
            [i for i in _match(sub) if i["type"] == "meeting"], []
        )


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


class UpcomingMeetingTests(TestCase):
    def _future(self, days, hour=9):
        from django.utils import timezone as dj_tz

        # Build in LOCAL time — Event.start_date carries a tz offset and the
        # sidebar localizes for display, so a 9 AM built in UTC would render
        # as 2 AM Pacific. Microseconds stripped: the column is varchar(25).
        when = dj_tz.localtime(dj_tz.now() + timedelta(days=days)).replace(
            hour=hour, minute=30, second=0, microsecond=0
        )
        return when.isoformat()

    def _sub_with_committee(self, email="up@example.org"):
        rep = fixtures.councilmember("Robert Kettle", "District 7")
        fixtures.committee_membership(rep, fixtures.committee("Public Safety"))
        return fixtures.subscriber(email, followed_reps=[rep])

    def test_upcoming_meeting_of_followed_committee(self):
        sub = self._sub_with_committee()
        fixtures.meeting("Public Safety Committee", start_date=self._future(3))
        items = personalization.upcoming_meetings(sub.preferences)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "upcoming")
        self.assertEqual(items[0]["time_label"], "9:30 AM")

    def test_past_and_far_future_excluded(self):
        sub = self._sub_with_committee("up2@example.org")
        fixtures.meeting("Public Safety Committee", start_date=RECENT)
        fixtures.meeting(
            "Public Safety Committee", start_date=self._future(30)
        )
        self.assertEqual(
            personalization.upcoming_meetings(sub.preferences), []
        )

    def test_cancelled_excluded(self):
        sub = self._sub_with_committee("up3@example.org")
        event = fixtures.meeting(
            "Public Safety Committee", start_date=self._future(2)
        )
        event.status = "cancelled"
        event.save()
        self.assertEqual(
            personalization.upcoming_meetings(sub.preferences), []
        )

    def test_unrelated_committee_excluded(self):
        sub = self._sub_with_committee("up4@example.org")
        fixtures.meeting("Land Use Committee", start_date=self._future(2))
        self.assertEqual(
            personalization.upcoming_meetings(sub.preferences), []
        )

    def test_full_city_council_upcoming_included_for_everyone(self):
        fixtures.meeting("City Council", start_date=self._future(2))
        sub = fixtures.subscriber("councilup@example.org", issue_areas=["Housing"])
        items = personalization.upcoming_meetings(sub.preferences)
        self.assertEqual([i["title"] for i in items], ["City Council"])

    def test_district_rep_committee_matches_soonest_first(self):
        rep = fixtures.councilmember("Joy Hollingsworth", "District 3")
        fixtures.committee_membership(rep, fixtures.committee("Parks"))
        sub = fixtures.subscriber(
            "up5@example.org", district_obj=fixtures.district("3")
        )
        far = fixtures.meeting("Parks Committee", start_date=self._future(5))
        near = fixtures.meeting("Parks Committee", start_date=self._future(2))
        items = personalization.upcoming_meetings(sub.preferences)
        self.assertEqual([i["id"] for i in items], [near.id, far.id])


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
