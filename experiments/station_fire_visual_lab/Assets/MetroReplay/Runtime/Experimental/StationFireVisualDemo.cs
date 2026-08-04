using System.Collections;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    /// <summary>
    /// Visual-only fire overlay for the isolated station-layout experiment.
    /// Passenger positions, directions and evacuation routes remain the frozen
    /// replay output; the fire does not participate in routing or simulation.
    /// </summary>
    [DefaultExecutionOrder(1000)]
    public sealed class StationFireVisualDemo : MonoBehaviour
    {
        public const bool Enabled = true;

        private const string LevelId = "b1_concourse";
        private const string FireResourcePath =
            "MetroFire/Particles/VFX_Fire_01_Medium_Smoke";
        private const float StartTime = 84f;
        private const float LoopEndTime = 145f;

        private ReplayApplicationRoot _application;
        private Light _fireLight;
        private StationElementTrialLayer _elementTrialLayer;
        private GUIStyle _titleStyle;
        private GUIStyle _bodyStyle;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void CreateDemoController()
        {
            if (!Enabled || Object.FindFirstObjectByType<StationFireVisualDemo>() != null)
                return;

            var controller = new GameObject("Station Fire Visual Demo");
            DontDestroyOnLoad(controller);
            controller.AddComponent<StationFireVisualDemo>();
        }

        private IEnumerator Start()
        {
            while ((_application = Object.FindFirstObjectByType<ReplayApplicationRoot>()) == null
                   || _application.Data == null
                   || _application.Clock == null)
            {
                yield return null;
            }

            BuildFire(_application.Data);
            StationFireOperationsVisuals.Build(_application.Data, transform);
            _elementTrialLayer = new StationElementTrialLayer();
            var trialTask = _elementTrialLayer.BuildAsync(
                _application.Data,
                transform,
                UnityEngine.Application.streamingAssetsPath);
            while (!trialTask.IsCompleted)
                yield return null;
            if (trialTask.IsFaulted)
                Debug.LogException(trialTask.Exception?.GetBaseException() ?? trialTask.Exception);
            _application.Clock.Seek(StartTime);
            _application.Clock.SetSpeed(1f);
            _application.Clock.Play();

            // Allow ReplayApplicationRoot to sample the B1 crowd once, then set a
            // wider view containing both the fire and the exit-bound runners.
            yield return null;
            ConfigureCamera(_application.Data);
        }

        private void Update()
        {
            if (_application?.Clock == null)
                return;

            if (_application.Clock.Time >= LoopEndTime)
            {
                _application.Clock.Seek(StartTime);
                _application.Clock.Play();
            }

            if (_fireLight != null)
            {
                var flicker = Mathf.PerlinNoise(Time.unscaledTime * 7.1f, 0.37f);
                _fireLight.intensity = Mathf.Lerp(1600f, 2500f, flicker);
            }
        }

        private void BuildFire(ReplayData data)
        {
            var prototype = Resources.Load<GameObject>(FireResourcePath);
            if (prototype == null)
            {
                Debug.LogError($"Station fire prefab was not found at Resources/{FireResourcePath}.");
                return;
            }

            // Actual B1 station-plan coordinates, beside the central ad/planter.
            // At t=84 s the dominant passenger flow has already passed this point
            // and is moving toward the right-side exit-gate bank.
            var position = data.ToWorld(44.7f, 13.5f, LevelId, 0.08f);
            var fire = Instantiate(prototype, position, Quaternion.identity);
            fire.name = "B1 Visual Fire · Non-authoritative";
            fire.transform.localScale = Vector3.one * 0.92f;

            foreach (var audioSource in fire.GetComponentsInChildren<AudioSource>(true))
                audioSource.enabled = false;

            var lightObject = new GameObject("B1 Fire Flicker Light");
            lightObject.transform.SetParent(fire.transform, false);
            lightObject.transform.localPosition = new Vector3(0f, 1.15f, 0f);
            _fireLight = lightObject.AddComponent<Light>();
            _fireLight.type = LightType.Point;
            _fireLight.color = new Color(1f, 0.29f, 0.055f);
            _fireLight.range = 9f;
            _fireLight.intensity = 2100f;
            _fireLight.shadows = LightShadows.Soft;
            HdrpStationLook.EnsureAdditionalLightData(_fireLight);
        }

        private static void ConfigureCamera(ReplayData data)
        {
            var camera = Object.FindFirstObjectByType<OrbitCameraController>();
            if (camera == null)
                return;

            var target = data.ToWorld(53.2f, 14.1f, LevelId, 0.55f);
            camera.SetView(target, 21.5f, 165f, 8f);
        }

        private void OnGUI()
        {
            EnsureStyles();
            var width = Mathf.Min(470f, Screen.width - 32f);
            var panel = new Rect(16f, 16f, width, 78f);
            var previous = GUI.color;
            GUI.color = new Color(0.075f, 0.045f, 0.035f, 0.92f);
            GUI.DrawTexture(panel, Texture2D.whiteTexture);
            GUI.color = previous;
            GUI.Label(new Rect(panel.x + 14f, panel.y + 9f, panel.width - 28f, 26f),
                "B1 站厅火灾视觉样例", _titleStyle);
            GUI.Label(new Rect(panel.x + 14f, panel.y + 38f, panel.width - 28f, 30f),
                "冻结疏散轨迹 · 火焰、人员与全部试装设施均未参与路径计算", _bodyStyle);
        }

        private void OnDestroy()
        {
            _elementTrialLayer?.Dispose();
        }

        private void EnsureStyles()
        {
            if (_titleStyle != null)
                return;

            _titleStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = 20,
                fontStyle = FontStyle.Bold,
                normal = { textColor = new Color(1f, 0.78f, 0.52f) }
            };
            _bodyStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = 14,
                normal = { textColor = new Color(0.94f, 0.94f, 0.94f) }
            };
        }
    }
}
