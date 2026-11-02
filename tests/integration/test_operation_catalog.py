from tests.support.cleanup_case import case


def test_consumed_token_reuses_same_operation(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        first = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        again = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert first["operation_id"] == again["operation_id"]
        assert first["items"] == again["items"]
