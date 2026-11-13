from cli.commands.language_encoder import same_model_config


def test_checkpointing_does_not_change_model_identity():
    base = {"d_model": 768, "vocab_size": 48000, "gradient_checkpointing": False}
    assert same_model_config(base, {**base, "gradient_checkpointing": True})


def test_other_differences_still_reject():
    base = {"d_model": 768, "vocab_size": 48000, "gradient_checkpointing": False}
    assert not same_model_config(base, {**base, "vocab_size": 32000})
    assert not same_model_config(None, base)
