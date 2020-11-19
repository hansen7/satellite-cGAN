from imports import *
from metrics import *
from models import *

models_dict = {"unet": UNet, "fpn": FPN}

models_args_dict = {"unet": ["no_skips"], "fpn": ["resnet_encoder"]}

metric_dict = {
    "bce_loss": nn.BCELoss,
    "mse_loss": nn.MSELoss,
    "ternaus_loss": TernausLossFunc,
    "targetted_ternaus_and_MSE": TargettedTernausAndMSE,
    "dice_coefficient": DiceCoefficient,
}

req_args_dict = {
    "bce_loss": [],
    "mse_loss": [],
    "ternaus_loss": ["beta", "l"],
    "targetted_ternaus_and_MSE": [
        "cls_layer",
        "reg_layer",
        "cls_lambda",
        "reg_lambda",
        "beta",
        "l",
    ],
    "dice_coefficient": [],
}

TASK_CHANNELS = {
    "reg": {"channels": ["NDVI", "NDBI", "NDWI"], "classes": ["LSTN2"]},
    "cls": {"channels": ["NDVI", "NDBI", "NDWI"], "classes": ["UHI"]},
    "mix": {"channels": ["NDVI", "NDBI", "NDWI"], "classes": ["LSTN", "UHI"]},
}


def normalise_loss_factor(model, comparison_loss_factor):

    if model.discriminator:
        loss_mag = (1 + comparison_loss_factor ** 2) ** 0.5
    else:
        loss_mag, comparison_loss_factor = 1, 1
    comparison_loss_factor /= loss_mag

    return comparison_loss_factor, loss_mag


def landsat_train_test_dataset(
    data_dir,
    channels: List[str],
    classes: List[str],
    test_size=0.3,
    train_size=None,
    random_state=None,
    purge_data=False,
):

    if train_size == None:
        train_size = 1.0 - test_size
    try:
        assert test_size + train_size <= 1.0
    except AssertionError:
        raise AssertionError("test_size + train_size > 1, which is not allowed")

    groups = group_bands(data_dir, channels + classes)
    if purge_data:
        groups = purge_groups(groups)

    train_groups, test_groups = train_test_split(
        groups, test_size=test_size, train_size=train_size, random_state=random_state
    )
    record_groups(train_groups=train_groups, test_groups=test_groups)

    print(
        f"{len(train_groups)} training instances, {len(test_groups)} testing instances"
    )

    train_dataset = LandsatDataset(
        groups=train_groups, channels=channels, classes=classes
    )
    test_dataset = LandsatDataset(
        groups=test_groups, channels=channels, classes=classes
    )

    return train_dataset, test_dataset


def prepare_training(config):

    if config.task == "reg":
        sigmoid_channels = [False]
    elif config.task == "cls":
        sigmoid_channels = [True]
    elif config.task == "mix":
        sigmoid_channels = [None, None]
        sigmoid_channels[config.reg_layer] = False
        sigmoid_channels[config.cls_layer] = True
    else:
        raise ValueError(f"{config.task} is not a recognised task (reg, cls, mix)")

    cGAN = ConditionalGAN(
        classes=config.classes,
        channels=config.channels,
        dis_dropout=config.dis_dropout,
        gen_dropout=config.gen_dropout,
        no_discriminator=config.no_discriminator,
        sigmoid_channels=sigmoid_channels,
        generator_class=config.model,
        generator_params=config.model_parameters,
    )

    comparison_loss_fn = metric_dict[config.comparison_loss_fn](
        **config.loss_parameters
    )
    test_metric = metric_dict[config.test_metric](**config.test_parameters)
    adversarial_loss_fn = nn.BCELoss()

    if config.wandb:
        wandb.watch(cGAN)

    optimizer_G = torch.optim.Adam(cGAN.generator.parameters(), lr=config.lr)
    if config.no_discriminator:
        optimizer_D = None
    else:
        optimizer_D = torch.optim.Adam(cGAN.discriminator.parameters(), lr=config.lr)

    train_dataset, test_dataset = landsat_train_test_dataset(
        data_dir=config.data_dir,
        channels=config.channels,
        classes=config.classes,
        test_size=config.test_size,
        train_size=config.train_size,
        random_state=config.random_state,
        purge_data=config.purge_data,
    )

    test_dataloader = DataLoader(
        test_dataset, batch_size=config.batch_size  # collate_fn=skip_tris
    )  # Change to own batch size?

    train_num_steps = len(train_dataloader)
    test_num_steps = len(test_dataloader)
    print(
        "Starting training for {} epochs of {} training steps and {} evaluation steps".format(
            config.num_epochs, train_num_steps, test_num_steps
        )
    )

    return (
        cGAN,
        comparison_loss_fn,
        test_metric,
        adversarial_loss_fn,
        optimizer_D,
        optimizer_G,
        train_dataset,
        test_dataloader,
        train_num_steps,
        test_num_steps,
    )


def generate_adversarial_loss(cGAN, preds, adversarial_loss_fn):

    reshaped_preds = reshape_for_discriminator(preds, len(cGAN.classes))
    gene_targets = torch.zeros(dis_probs_gene.shape)
    dis_probs_gene = cGAN.discriminator.forward(reshaped_preds, reorder=False)
    generator_adversarial_loss_gene = adversarial_loss_fn(dis_probs_gene, gene_targets)
    generator_adversarial_loss_gene /= loss_mag

    reshaped_detached_preds = reshape_for_discriminator(
        preds.detach(), len(cGAN.classes)
    )
    dis_probs_gene = cGAN.discriminator.forward(reshaped_detached_preds, reorder=False)
    adversarial_loss_gene = adversarial_loss_fn(dis_probs_gene, gene_targets)

    dis_targets_real = torch.cat([torch.eye(len(cGAN.classes)) for _ in preds])
    reshaped_labels = reshape_for_discriminator2(labels, len(cGAN.classes))
    dis_probs_real = cGAN.discriminator.forward(reshaped_labels, reorder=False)
    adversarial_loss_real = adversarial_loss_fn(dis_probs_real, dis_targets_real)

    discriminator_adversarial_loss = (adversarial_loss_real + adversarial_loss_gene) / (
        2 * loss_mag
    )

    return generator_adversarial_loss_gene, discriminator_adversarial_loss
