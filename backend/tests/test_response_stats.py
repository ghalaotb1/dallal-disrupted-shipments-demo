from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.response_stats import ResponseStats


def test_prior_then_learning_changes_value_inputs_within_context_only():
    s = iq.spec("ask_courier_status")
    p0 = iq.response_prob(s, {})
    st = ResponseStats()
    for _ in range(40):
        st.update("ask_courier_status", False)  # nobody ever answers
    with st.apply():
        assert iq.response_prob(s, {}) < 0.3 * p0
    assert iq.response_prob(s, {}) == p0  # the override does not leak outside the context


def test_latency_is_learned_and_shrunk():
    s = iq.spec("ask_courier_status")
    base = iq.expected_latency_min(s)
    st = ResponseStats()
    for _ in range(30):
        st.update("ask_courier_status", True, 60.0)
    with st.apply():
        assert iq.expected_latency_min(s) > 3 * base
    st2 = ResponseStats()
    st2.update("ask_courier_status", True, 60.0)  # one observation barely moves the prior
    with st2.apply():
        assert iq.expected_latency_min(s) < 2 * base


def test_service_learns_from_closed_inquiries():
    from dallal.channels import whatsapp as wa
    from dallal.data.augment.scenarios import SCENARIOS
    from dallal.service import OpsService
    from dallal.store import Store

    svc = OpsService(Store(":memory:"), wa.SandboxProvider(), time_scale=1.0)
    r = svc.investigate(SCENARIOS["developing_disruption"](11), "ar")
    rid = r["run_id"] if "run_id" in r else r["run"]["run_id"]
    iid = svc.view_run(rid)["inquiries_live"][0]["inquiry_id"]
    svc.expire(iid)
    assert svc.response_stats().asked.get("ask_courier_status", 0) >= 1
