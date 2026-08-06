from __future__ import annotations

import unittest

from scripts import run_metro_stress_matrix as stress


PLATFORM_ID = "platform:default:down"


class TrainServiceDisruptionTests(unittest.TestCase):
    def _args(self, *extra: str):
        return stress.build_parser().parse_args(
            [
                "--pairs",
                "0:0",
                "--minutes",
                "20",
                "--tick-seconds",
                "5",
                "--design-template",
                "visual_demo_station",
                "--initial-train-offset-seconds",
                "75",
                "--train-headway-seconds",
                "240",
                "--train-dwell-seconds",
                "35",
                *extra,
            ]
        )

    def _model(self, *extra: str):
        args = self._args(*extra)
        scenario = stress.make_scenario(args, stress.StressCase(0, 0, 42))
        return stress.MetroStationModel(scenario, seed=42)

    def _step_through(self, model, time_seconds: int) -> None:
        while model.current_time_seconds <= time_seconds:
            model.step()

    def test_cli_parser_preserves_colons_in_platform_id(self) -> None:
        event = stress.parse_train_event(f"60:suspend:{PLATFORM_ID}")

        self.assertEqual(60, event.at_seconds)
        self.assertEqual("suspend", event.action)
        self.assertEqual(PLATFORM_ID, event.platform_id)

    def test_schedule_rejects_unaligned_out_of_order_and_invalid_lifecycle(self) -> None:
        invalid_schedules = (
            (f"7:suspend:{PLATFORM_ID}",),
            (f"10:suspend:{PLATFORM_ID}", f"5:resume:{PLATFORM_ID}"),
            (f"10:resume:{PLATFORM_ID}",),
            (f"10:suspend:{PLATFORM_ID}", f"15:suspend:{PLATFORM_ID}"),
            (f"1200:suspend:{PLATFORM_ID}",),
        )

        for schedule in invalid_schedules:
            cli = [item for event in schedule for item in ("--train-event", event)]
            with self.subTest(schedule=schedule):
                args = self._args(*cli)
                with self.assertRaises(ValueError):
                    stress.make_scenario(args, stress.StressCase(0, 0, 42))

    def test_unknown_platform_fails_at_model_startup(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown platforms"):
            self._model("--train-event", "0:suspend:missing:platform")

    def test_continuous_suspension_cancels_each_scheduled_arrival(self) -> None:
        model = self._model(
            "--train-event",
            f"0:suspend:{PLATFORM_ID}",
            "--train-event",
            f"600:resume:{PLATFORM_ID}",
        )

        self._step_through(model, 600)

        train = model.train
        controller = model.train_disruption_controller
        self.assertEqual(3, train.cancelled_trains)
        self.assertEqual([75.0, 315.0, 555.0], [e["time_seconds"] for e in controller.cancelled_arrivals])
        self.assertEqual(795, train.next_arrival_step * model.scenario.tick_seconds)
        self.assertFalse(controller.is_suspended(PLATFORM_ID))
        self.assertEqual(0, controller.arrival_during_suspension_violations())

    def test_suspending_during_dwell_allows_current_train_to_depart(self) -> None:
        model = self._model(
            "--train-event",
            f"80:suspend:{PLATFORM_ID}",
            "--train-event",
            f"400:resume:{PLATFORM_ID}",
        )

        self._step_through(model, 315)

        self.assertEqual(1, model.train.departed_trains)
        self.assertEqual(1, model.train.cancelled_trains)
        self.assertEqual("boarding", model.train_disruption_controller.applied_events[0].train_state)
        self.assertEqual(315.0, model.train_disruption_controller.cancelled_arrivals[0]["time_seconds"])

    def test_resume_at_scheduled_arrival_allows_train_to_arrive(self) -> None:
        model = self._model(
            "--train-event",
            f"0:suspend:{PLATFORM_ID}",
            "--train-event",
            f"315:resume:{PLATFORM_ID}",
        )

        self._step_through(model, 315)

        self.assertEqual(1, model.train.cancelled_trains)
        self.assertEqual("boarding", model.train.state)
        self.assertEqual([315.0], [e["time_seconds"] for e in model.train_disruption_controller.arrivals])
        self.assertEqual(0, model.train_disruption_controller.arrival_during_suspension_violations())

    def test_arrival_during_suspension_is_an_acceptance_failure(self) -> None:
        decision = stress.assess_stress_row(
            {
                "status": "ok",
                "train_arrival_during_suspension_violations": 1,
            },
            min_completion_rate=None,
            max_final_station_persons=None,
        )

        self.assertEqual("fail", decision["acceptance_status"])
        self.assertIn("suspended", decision["acceptance_issues"][0])

    def test_cancelled_train_alighting_does_not_move_to_recovered_train(self) -> None:
        args = self._args(
            "--pairs",
            "0:60",
            "--demand-minutes",
            "3",
            "--train-event",
            f"0:suspend:{PLATFORM_ID}",
            "--train-event",
            f"600:resume:{PLATFORM_ID}",
        )
        model = stress.MetroStationModel(
            stress.make_scenario(args, stress.StressCase(0, 60, 42)),
            seed=42,
        )

        self._step_through(model, 600)
        self.assertEqual(0, model.pending_alighting_groups)
        self.assertEqual(0, model.spawned_persons)
        self.assertEqual(3, model.unbound_not_alighted_persons)
        self.assertEqual("train_alighting_manifest_unavailable", model.run_outcome_code)

        self._step_through(model, 795)

        self.assertEqual(0, model.pending_alighting_groups)
        self.assertEqual(0, model.spawned_persons)
        self.assertEqual(3, model.unbound_not_alighted_persons)

    def test_unrecovered_alighting_demand_reduces_completion_rate(self) -> None:
        args = self._args(
            "--pairs",
            "0:60",
            "--demand-minutes",
            "3",
            "--train-event",
            f"0:suspend:{PLATFORM_ID}",
            "--min-completion-rate",
            "1",
        )
        case = stress.StressCase(0, 60, 42)
        model = stress.MetroStationModel(stress.make_scenario(args, case), seed=42)
        frames = model.run()
        row = stress.summarize_run(
            args=args,
            case=case,
            frames=frames,
            elapsed_seconds=0.0,
            model=model,
        )
        row.update(
            stress.assess_stress_row(
                row,
                min_completion_rate=1.0,
                max_final_station_persons=None,
            )
        )

        self.assertEqual(3, row["scheduled_demand_persons"])
        self.assertEqual(3, row["unspawned_alighting_persons_final"])
        self.assertEqual(3, row["not_alighted_persons_final"])
        self.assertEqual(0, row["demand_accounting_error_persons"])
        self.assertEqual(0.0, row["completion_rate"])
        self.assertEqual("fail", row["acceptance_status"])


if __name__ == "__main__":
    unittest.main()
