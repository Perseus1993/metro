using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace MetroReplay.Tests
{
    internal static class ReplayTestData
    {
        public static string ValidJson(
            int passengerCount = 1,
            bool includeElevatorEvent = true,
            bool cleared = false)
        {
            var startPassengers = new JArray();
            var endPassengers = new JArray();
            var passengerIds = new JArray();
            for (var i = 0; i < passengerCount; i++)
            {
                var id = i + 1;
                passengerIds.Add(id);
                startPassengers.Add(Passenger(id, 2f + i * 0.05f, 2f, "b1", "walking"));
                if (!cleared)
                    endPassengers.Add(Passenger(id, 2f + i * 0.05f, 22f, "b2", "walking"));
            }

            var events = new JArray();
            if (includeElevatorEvent)
            {
                events.Add(new JObject
                {
                    ["event_id"] = 9,
                    ["facility_id"] = "vertical:elevator:test",
                    ["facility_kind"] = "elevator",
                    ["passenger_ids"] = passengerIds,
                    ["start_time"] = 0f,
                    ["board_end_time"] = 2f,
                    ["arrive_time"] = 8f,
                    ["end_time"] = 10f,
                    ["from_level"] = "b1",
                    ["to_level"] = "b2",
                    ["start_position"] = new JArray(2f, 2f),
                    ["end_position"] = new JArray(2f, 22f)
                });
            }

            var scene = new JObject
            {
                ["schema_version"] = "station_scene.v1",
                ["scene_id"] = "test",
                ["levels"] = new JArray(
                    Level("b1", "B1", -6f, 0f),
                    Level("b2", "B2", -14f, 20f)),
                ["entities"] = new JArray(
                    Entity("floor:b1", "walkable_area", "b1", RectPoints(0f), "polygon"),
                    Entity("floor:b2", "walkable_area", "b2", RectPoints(20f), "polygon"),
                    Entity("gate:test", "gate", "b1", new JArray(), "rect", 2f, 2f, 2f, 1f),
                    Connector("escalator:test", "escalator"),
                    Connector("elevator:test", "elevator")),
                ["relations"] = new JArray(),
                ["runtime_bindings"] = new JArray(
                    new JObject { ["scene_entity_id"] = "gate:test" }),
                ["topology"] = new JObject()
            };

            var trace = new JObject
            {
                ["schema_version"] = "simulation_trace.v1",
                ["run_id"] = "test-run",
                ["metadata"] = new JObject
                {
                    ["replay_fidelity"] = new JObject
                    {
                        ["position_authority"] = "simulation_trace.snapshots",
                        ["snapshot_interval_seconds"] = 1f,
                        ["facility_motion_authority"] = "simulation_trace.facility_events",
                        ["visual_tracks_authoritative"] = false
                    },
                    ["routing_evidence"] = new JObject
                    {
                        ["decision_count"] = 2,
                        ["plugin_ids"] = new JArray("metro.shortest_path")
                    }
                },
                ["snapshots"] = new JArray(
                    new JObject { ["time_seconds"] = 0f, ["passengers"] = startPassengers },
                    new JObject { ["time_seconds"] = 10f, ["passengers"] = endPassengers }),
                ["facility_events"] = events
            };

            var clearanceAudit = new JObject
            {
                ["cleared"] = cleared,
                ["outcome"] = cleared ? "cleared" : "incomplete",
                ["total_agents"] = passengerCount,
                ["completed_agents"] = cleared ? passengerCount : 0,
                ["remaining_agents"] = cleared ? 0 : passengerCount,
                ["clearance_time_s"] = cleared ? JToken.FromObject(10f) : JValue.CreateNull()
            };

            return new JObject
            {
                ["schema_version"] = "visualization_bundle.v1",
                ["source_run_id"] = "test-run",
                ["clearance_audit"] = clearanceAudit,
                ["simulation_trace"] = trace,
                ["replay_package"] = new JObject
                {
                    ["schema_version"] = "replay_package.v2",
                    ["station_scene"] = scene
                }
            }.ToString();
        }

        public static string ValidTrainJson()
        {
            var root = JObject.Parse(ValidJson(includeElevatorEvent: false));
            var snapshots = (JArray)root["simulation_trace"]!["snapshots"]!;
            ((JObject)snapshots[0]!)["trains"] = new JArray(
                Train("away", nextArrivalSeconds: 10f));
            ((JObject)snapshots[1]!)["trains"] = new JArray(
                Train("boarding", nextArrivalSeconds: 10f));
            return root.ToString();
        }

        public static string ValidPlatformTrainJson()
        {
            var root = JObject.Parse(ValidTrainJson());
            var entities = (JArray)root["replay_package"]!["station_scene"]!["entities"]!;
            for (var index = 0; index < 6; index++)
            {
                entities.Add(Entity(
                    "platform_edge:test:" + (index + 1),
                    "platform_edge",
                    "b2",
                    new JArray(),
                    "rect",
                    2.5f + index * 3f,
                    28f,
                    2.2f,
                    0.22f));
            }

            var snapshots = (JArray)root["simulation_trace"]!["snapshots"]!;
            var passengers = snapshots[1]!["passengers"]!.DeepClone();
            snapshots.Add(new JObject
            {
                ["time_seconds"] = 15f,
                ["passengers"] = passengers.DeepClone(),
                ["trains"] = new JArray(Train("boarding", nextArrivalSeconds: 10f))
            });
            snapshots.Add(new JObject
            {
                ["time_seconds"] = 20f,
                ["passengers"] = passengers.DeepClone(),
                ["trains"] = new JArray(Train("away", nextArrivalSeconds: 10f))
            });
            return root.ToString();
        }

        private static JObject Passenger(int id, float x, float y, string level, string state)
        {
            return new JObject
            {
                ["id"] = id,
                ["x"] = x,
                ["y"] = y,
                ["current_level_id"] = level,
                ["state"] = state,
                ["intent"] = "enter_and_board",
                ["n"] = 1
            };
        }

        private static JObject Train(string state, float nextArrivalSeconds)
        {
            return new JObject
            {
                ["id"] = 26,
                ["line_id"] = "default",
                ["direction"] = "down",
                ["platform_id"] = "platform:default:down",
                ["state"] = state,
                ["current_load_persons"] = 0,
                ["last_departed_load_persons"] = 0,
                ["departure_elapsed_seconds"] = null,
                ["departed_trains"] = 0,
                ["cancelled_trains"] = 0,
                ["next_arrival_seconds"] = nextArrivalSeconds,
                ["service_suspended"] = false,
                ["capacity_persons"] = 1200
            };
        }

        private static JObject Level(string id, string label, float elevation, float yOffset)
        {
            return new JObject
            {
                ["level_id"] = id,
                ["label"] = label,
                ["elevation"] = elevation,
                ["footprint"] = RectPoints(yOffset)
            };
        }

        private static JArray RectPoints(float yOffset)
        {
            return new JArray(
                new JArray(0f, yOffset),
                new JArray(20f, yOffset),
                new JArray(20f, yOffset + 10f),
                new JArray(0f, yOffset + 10f));
        }

        private static JObject Entity(
            string id,
            string kind,
            string level,
            JArray points,
            string shape,
            float x = 0f,
            float y = 0f,
            float width = 0f,
            float height = 0f)
        {
            return new JObject
            {
                ["entity_id"] = id,
                ["kind"] = kind,
                ["label"] = id,
                ["geometry"] = new JObject
                {
                    ["shape"] = shape,
                    ["x_m"] = x,
                    ["y_m"] = y,
                    ["width_m"] = width,
                    ["height_m"] = height,
                    ["rotation_deg"] = 0f,
                    ["points_m"] = points
                },
                ["level_ids"] = new JArray(level)
            };
        }

        private static JObject Connector(string id, string kind)
        {
            return new JObject
            {
                ["entity_id"] = id,
                ["kind"] = kind,
                ["label"] = id,
                ["geometry"] = new JObject
                {
                    ["shape"] = "polyline",
                    ["x_m"] = 0f,
                    ["y_m"] = 0f,
                    ["width_m"] = 0f,
                    ["height_m"] = 0f,
                    ["rotation_deg"] = 0f,
                    ["points_m"] = new JArray(new JArray(2f, 2f), new JArray(2f, 22f))
                },
                ["level_ids"] = new JArray("b1", "b2")
            };
        }
    }
}
