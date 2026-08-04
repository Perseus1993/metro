using MetroReplay.Infrastructure;
using Newtonsoft.Json.Linq;
using NUnit.Framework;

namespace MetroReplay.Tests
{
    public sealed class ReplayContractReaderTests
    {
        [Test]
        public void ReadsTwoLevelReplayContract()
        {
            var data = ReplayContractReader.Read(ReplayTestData.ValidJson());

            Assert.That(data.Levels.Count, Is.EqualTo(2));
            Assert.That(data.Entities.Count, Is.EqualTo(5));
            Assert.That(data.Frames.Count, Is.EqualTo(2));
            Assert.That(data.FacilityEvents.Count, Is.EqualTo(1));
            Assert.That(data.Duration, Is.EqualTo(10f));
            Assert.That(data.ClearanceAudit.IsAvailable, Is.True);
            Assert.That(data.ClearanceAudit.Cleared, Is.False);
            Assert.That(data.FinalVisiblePassengers, Is.EqualTo(1));
            Assert.That(data.Fidelity.IsAuthoritative, Is.True);
            Assert.That(data.Fidelity.SnapshotIntervalSeconds, Is.EqualTo(1f));
            Assert.That(data.Fidelity.RoutingPluginIds, Does.Contain("metro.shortest_path"));
            Assert.That(data.Fidelity.RoutingDecisionCount, Is.EqualTo(2));
        }

        [Test]
        public void ReadsAuthoritativeTrainSnapshots()
        {
            var data = ReplayContractReader.Read(ReplayTestData.ValidTrainJson());

            Assert.That(data.Frames[0].Trains.Count, Is.EqualTo(1));
            Assert.That(data.Frames[0].Trains[26].State, Is.EqualTo("away"));
            Assert.That(data.Frames[0].Trains[26].NextArrivalSeconds, Is.EqualTo(10f));
            Assert.That(data.Frames[1].Trains[26].State, Is.EqualTo("boarding"));
        }

        [Test]
        public void ReadsCompleteClearanceEvidenceAndEmptyFinalFrame()
        {
            var data = ReplayContractReader.Read(ReplayTestData.ValidJson(300, cleared: true));

            Assert.That(data.ClearanceAudit.Cleared, Is.True);
            Assert.That(data.ClearanceAudit.TotalPassengers, Is.EqualTo(300));
            Assert.That(data.ClearanceAudit.CompletedPassengers, Is.EqualTo(300));
            Assert.That(data.ClearanceAudit.RemainingPassengers, Is.Zero);
            Assert.That(data.ClearanceAudit.ClearanceTime, Is.EqualTo(10f));
            Assert.That(data.FinalVisiblePassengers, Is.Zero);
        }

        [Test]
        public void RejectsClearedAuditWhenFinalFrameStillContainsPassengers()
        {
            var json = JObject.Parse(ReplayTestData.ValidJson());
            json["clearance_audit"]!["cleared"] = true;
            json["clearance_audit"]!["outcome"] = "cleared";
            json["clearance_audit"]!["completed_agents"] = 1;
            json["clearance_audit"]!["remaining_agents"] = 0;
            json["clearance_audit"]!["clearance_time_s"] = 10f;

            var exception = Assert.Throws<ReplayContractException>(() => ReplayContractReader.Read(json.ToString()));
            StringAssert.Contains("final snapshot", exception!.Message);
        }

        [Test]
        public void RejectsUnknownEntityLevelReference()
        {
            var json = JObject.Parse(ReplayTestData.ValidJson());
            json["replay_package"]!["station_scene"]!["entities"]![0]!["level_ids"]![0] = "missing";

            var exception = Assert.Throws<ReplayContractException>(() => ReplayContractReader.Read(json.ToString()));
            StringAssert.Contains("unknown level", exception!.Message);
        }

        [Test]
        public void RejectsUnsupportedSchemaBeforeBuildingScene()
        {
            var json = JObject.Parse(ReplayTestData.ValidJson());
            json["schema_version"] = "visualization_bundle.v999";

            var exception = Assert.Throws<ReplayContractException>(() => ReplayContractReader.Read(json.ToString()));
            StringAssert.Contains("Unsupported", exception!.Message);
        }
    }
}
