from backend.services.model_registry import registry
from backend.services.resource_manager import resources


def test_catalog_contracts() -> None:
    for model in registry.all():
        assert model.id
        assert model.category in ("stt", "tts", "clone")
        assert model.license
        assert model.russian_status in ("confirmed", "verify", "none")
        assert isinstance(model.languages, list)
        for variant in registry.variants(model.id):
            assert variant.device in ("gpu", "cpu")
            assert variant.precision
            assert variant.vram_estimate_gb >= 0


def test_plan_for_installed_model() -> None:
    candidates = [model for model in registry.all() if any(v.install_state == "installed" for v in registry.variants(model.id))]
    if not candidates:
        return
    model = candidates[0]
    variant = registry.default_variant(model.id)
    assert variant is not None
    plan = resources.plan(model.id, variant.id)
    assert plan.verdict in ("fits", "tight", "no")
    assert plan.need_vram_gb >= 0
    assert plan.free_vram_gb >= 0



def test_resource_options_have_unique_ids() -> None:
    candidates = [
        model
        for model in registry.all()
        if any(v.install_state == "installed" for v in registry.variants(model.id))
    ]
    if not candidates:
        return

    model = candidates[0]
    variant = registry.default_variant(model.id)
    assert variant is not None
    memory = {
        "free_vram_gb": 0.1,
        "free_ram_gb": 8.0,
    }
    options = resources._options(model, variant, "gpu", memory, 4.0, "no")
    option_ids = [option["id"] for option in options]
    assert len(option_ids) == len(set(option_ids))
