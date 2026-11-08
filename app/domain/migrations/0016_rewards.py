"""C5: reward rules, entitlements and draws, and reward settings on a run. Old runs have none."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0015_navigation_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="quizrun",
            name="rewards_json",
            field=models.JSONField(default=dict),
        ),
        migrations.CreateModel(
            name="Draw",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("draw", "Draw"),
                            ("redraw", "Redraw"),
                            ("move_up", "Move Up"),
                            ("substitute", "Substitute"),
                        ],
                        max_length=20,
                    ),
                ),
                ("admin_id", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("eligible_count", models.PositiveIntegerField()),
                ("eligible_set_hash", models.CharField(max_length=64)),
                ("algorithm", models.CharField(max_length=64)),
                ("rules_version", models.CharField(max_length=64)),
                ("reason", models.CharField(blank=True, max_length=200)),
                ("audit_json", models.JSONField(default=dict)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="children",
                        to="domain.draw",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="draws",
                        to="domain.quizrun",
                    ),
                ),
            ],
            options={
                "db_table": "draw",
            },
        ),
        migrations.CreateModel(
            name="DrawEntry",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("pseudonym", models.CharField(max_length=64)),
                ("position", models.PositiveIntegerField()),
                (
                    "role",
                    models.CharField(
                        choices=[("winner", "Winner"), ("alternate", "Alternate"), ("out", "Out")],
                        max_length=10,
                    ),
                ),
                (
                    "draw",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entries",
                        to="domain.draw",
                    ),
                ),
                (
                    "participant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="draw_entries",
                        to="domain.participant",
                    ),
                ),
            ],
            options={
                "db_table": "draw_entry",
            },
        ),
        migrations.CreateModel(
            name="RewardRule",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("position", models.PositiveIntegerField(default=0)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("threshold", "Threshold"),
                            ("participation", "Participation"),
                            ("manual", "Manual"),
                            ("draw", "Draw"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "threshold_unit",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("percent", "Percent"),
                            ("points", "Points"),
                            ("correct", "Correct"),
                        ],
                        max_length=10,
                        null=True,
                    ),
                ),
                (
                    "threshold_value",
                    models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True),
                ),
                (
                    "min_unit",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("percent", "Percent"),
                            ("points", "Points"),
                            ("correct", "Correct"),
                        ],
                        max_length=10,
                        null=True,
                    ),
                ),
                (
                    "min_value",
                    models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True),
                ),
                ("winners", models.PositiveIntegerField(blank=True, null=True)),
                ("alternates", models.PositiveIntegerField(blank=True, null=True)),
                ("texts_json", models.JSONField(default=dict)),
                ("winners_public", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "quiz",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reward_rules",
                        to="domain.quiz",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reward_rules",
                        to="domain.quizrun",
                    ),
                ),
            ],
            options={
                "db_table": "reward_rule",
            },
        ),
        migrations.CreateModel(
            name="RewardEntitlement",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("granted", "Granted"),
                            ("handed_over", "Handed Over"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="granted",
                        max_length=20,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("auto", "Auto"), ("manual", "Manual"), ("draw", "Draw")],
                        max_length=10,
                    ),
                ),
                ("reason", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("changed_at", models.DateTimeField(blank=True, null=True)),
                ("changed_by", models.CharField(blank=True, max_length=64, null=True)),
                (
                    "attempt",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="domain.attempt",
                    ),
                ),
                (
                    "participant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entitlements",
                        to="domain.participant",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entitlements",
                        to="domain.quizrun",
                    ),
                ),
                (
                    "rule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="entitlements",
                        to="domain.rewardrule",
                    ),
                ),
            ],
            options={
                "db_table": "reward_entitlement",
            },
        ),
        migrations.AddField(
            model_name="draw",
            name="rule",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="draws",
                to="domain.rewardrule",
            ),
        ),
        migrations.AddIndex(
            model_name="rewardrule",
            index=models.Index(fields=["quiz", "run"], name="reward_rule_owner"),
        ),
        migrations.AddConstraint(
            model_name="rewardentitlement",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "cancelled"), _negated=True),
                fields=("rule", "participant"),
                name="entitlement_once_per_rule",
            ),
        ),
    ]
