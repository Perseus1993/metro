using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;

namespace HazardAssetLab
{
    public sealed class PanicRunner : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private AnimationClip panicClip;
        [SerializeField] private Transform destination;
        [SerializeField, Min(0f)] private float startDelay = 0.8f;
        [SerializeField, Min(0.1f)] private float speed = 3.6f;
        [SerializeField, Min(0.1f)] private float turnSpeed = 12f;
        [SerializeField, Min(0.05f)] private float stoppingDistance = 0.3f;
        [SerializeField, Min(0.1f)] private float animationSpeed = 1.35f;
        [SerializeField] private bool loopDemo = true;
        [SerializeField, Min(0.1f)] private float restartDelay = 1.2f;

        private PlayableGraph graph;
        private AnimationClipPlayable clipPlayable;
        private Vector3 startPosition;
        private float elapsed;
        private float arrivedElapsed;
        private bool started;
        private bool arrived;

        public bool IsRunning => started && !arrived;

        public void Configure(
            AnimationClip clip,
            Transform target,
            float delay,
            float moveSpeed,
            float playbackSpeed,
            float resetDelay = 1.2f)
        {
            panicClip = clip;
            destination = target;
            startDelay = Mathf.Max(0f, delay);
            speed = Mathf.Max(0.1f, moveSpeed);
            animationSpeed = Mathf.Max(0.1f, playbackSpeed);
            restartDelay = Mathf.Max(0.1f, resetDelay);
        }

        private void Start()
        {
            startPosition = transform.position;

            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>();
            }

            if (animator == null || panicClip == null)
            {
                Debug.LogError($"[PanicRunner] Missing Animator or panic clip on {name}.", this);
                enabled = false;
                return;
            }

            animator.applyRootMotion = false;
            graph = PlayableGraph.Create($"PanicRunner_{name}");
            graph.SetTimeUpdateMode(DirectorUpdateMode.GameTime);

            clipPlayable = AnimationClipPlayable.Create(graph, panicClip);
            clipPlayable.SetApplyFootIK(true);
            clipPlayable.SetApplyPlayableIK(false);
            clipPlayable.SetSpeed(animationSpeed);

            AnimationPlayableOutput output = AnimationPlayableOutput.Create(graph, "PanicSprint", animator);
            output.SetSourcePlayable(clipPlayable);

            graph.Play();
            clipPlayable.Pause();

            FaceDestinationImmediately();
        }

        private void Update()
        {
            if (arrived)
            {
                if (loopDemo)
                {
                    arrivedElapsed += Time.deltaTime;
                    if (arrivedElapsed >= restartDelay)
                    {
                        ResetRun();
                    }
                }

                return;
            }

            elapsed += Time.deltaTime;
            if (!started && elapsed >= startDelay)
            {
                started = true;
                if (clipPlayable.IsValid())
                {
                    clipPlayable.Play();
                }
            }

            if (!started || destination == null)
            {
                return;
            }

            LoopAnimationIfNeeded();

            Vector3 offset = destination.position - transform.position;
            offset.y = 0f;
            float distance = offset.magnitude;
            if (distance <= stoppingDistance)
            {
                arrived = true;
                arrivedElapsed = 0f;
                if (clipPlayable.IsValid())
                {
                    clipPlayable.Pause();
                }

                return;
            }

            Vector3 direction = offset / distance;
            float step = Mathf.Min(speed * Time.deltaTime, distance);
            transform.position += direction * step;

            Quaternion targetRotation = Quaternion.LookRotation(direction, Vector3.up);
            transform.rotation = Quaternion.Slerp(
                transform.rotation,
                targetRotation,
                1f - Mathf.Exp(-turnSpeed * Time.deltaTime));
        }

        private void LoopAnimationIfNeeded()
        {
            if (!clipPlayable.IsValid() || panicClip.length <= 0f)
            {
                return;
            }

            double clipTime = clipPlayable.GetTime();
            if (clipTime >= panicClip.length)
            {
                clipPlayable.SetTime(clipTime % panicClip.length);
            }
        }

        private void ResetRun()
        {
            transform.position = startPosition;
            elapsed = 0f;
            arrivedElapsed = 0f;
            started = false;
            arrived = false;

            if (clipPlayable.IsValid())
            {
                clipPlayable.SetTime(0d);
                clipPlayable.Pause();
            }

            FaceDestinationImmediately();
        }

        private void FaceDestinationImmediately()
        {
            if (destination == null)
            {
                return;
            }

            Vector3 direction = destination.position - transform.position;
            direction.y = 0f;
            if (direction.sqrMagnitude > 0.001f)
            {
                transform.rotation = Quaternion.LookRotation(direction.normalized, Vector3.up);
            }
        }

        private void OnDestroy()
        {
            if (graph.IsValid())
            {
                graph.Destroy();
            }
        }
    }
}
