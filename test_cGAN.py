#  Copyright (c) 2020. Puria and Hanchen, Email: {pr450, hw501}@cam.ac.uk
import os, torch, numpy as np, matplotlib.pyplot as plt
from pipelines.p_utils import slice_middle, read_raster
from models import ConditionalGAN
from matplotlib import cm
from glob import glob


def save_results_images(groups, cGAN, destination_dir, normalise_indices):
    for group in groups:
        image_id = ".".join(list(group.values())[0].split(".")[:-2])
        generate_results_image(image_id, cGAN, destination_dir, normalise_indices)


def generate_results_image(image_id, cGAN, destination_dir, normalise_indices):
    """Visualisation"""
    imV = slice_middle(
        read_raster(f"{image_id}.NDVI.tif")[0][:, :, np.newaxis], remove_nan=False
    )
    imB = slice_middle(
        read_raster(f"{image_id}.NDBI.tif")[0][:, :, np.newaxis], remove_nan=False
    )
    imW = slice_middle(
        read_raster(f"{image_id}.NDWI.tif")[0][:, :, np.newaxis], remove_nan=False
    )

    if isinstance(imW, type(None)):
        return None

    if normalise_indices:
        imV = (imV - np.nanmean(imV)) / np.nanstd(imV)
        imB = (imB - np.nanmean(imB)) / np.nanstd(imB)
        imW = (imW - np.nanmean(imW)) / np.nanstd(imW)

    imV[imV != imV] = 0
    imB[imB != imB] = 0
    imW[imW != imW] = 0
    image = np.dstack([imV, imB, imW])[np.newaxis, :, :, :]

    # LSTN2_real = read_raster(f"{image_id}.LSTN2.tif")[0][:, :, np.newaxis]
    try:
        LSTN2_real = read_raster(f"{image_id}.LSTN2.tif")[0][:, :, np.newaxis]
    except Exception as e:
        print(e)
        return None
    LSTN2_real = slice_middle(LSTN2_real).reshape(256, 256)

    LST_real = read_raster(f"{image_id}.LST.tif")[0][:, :, np.newaxis]
    LST_real = slice_middle(LST_real).reshape(256, 256)

    image_name = image_id.split("/")[-1]

    LSTN_pred = cGAN.generator(torch.tensor(image)).reshape(256, 256).detach().numpy()

    fig, axs = plt.subplots(2, 4, figsize=(40, 30))
    fig.suptitle(image_name, fontsize=50)

    axs[0, 0].imshow(imV, cmap="Greens")
    axs[0, 0].set_title("NDVI", fontsize=30)
    m = cm.ScalarMappable(cmap="Greens")
    m.set_clim(-1.0, 1.0)
    fig.colorbar(m, ax=axs[0, 0])

    axs[0, 1].imshow(imB, cmap="gray", vmin=-1.0, vmax=1.0)
    axs[0, 1].set_title("NDBI", fontsize=30)
    m = cm.ScalarMappable(cmap="gray")
    m.set_clim(-1.0, 1.0)
    fig.colorbar(m, ax=axs[0, 1])

    axs[0, 2].imshow(imW, cmap="Blues", vmin=-1.0, vmax=1.0)
    axs[0, 2].set_title("NDWI", fontsize=30)
    m = cm.ScalarMappable(cmap="Blues")
    m.set_clim(-1.0, 1.0)
    fig.colorbar(m, ax=axs[0, 2])

    axs[0, 3].imshow(LST_real, cmap="inferno")
    axs[0, 3].set_title("Real temperature (C)", fontsize=30)
    m = cm.ScalarMappable(cmap="inferno")
    m.set_clim(np.amin(LST_real), np.amax(LST_real))
    fig.colorbar(m, ax=axs[0, 3])

    axs[1, 0].imshow(LSTN2_real, cmap="magma")
    axs[1, 0].set_title("Real normalised\n temperature (LSTN2)", fontsize=30)
    m = cm.ScalarMappable(cmap="magma")
    m.set_clim(np.amin(LSTN2_real), np.amax(LSTN2_real))
    fig.colorbar(m, ax=axs[1, 0])

    axs[1, 1].imshow(LSTN_pred, cmap="magma")
    axs[1, 1].set_title("Predicted normalised\n temperature (LSTN2)", fontsize=30)
    m = cm.ScalarMappable(cmap="magma")
    m.set_clim(np.amin(LSTN_pred), np.amax(LSTN_pred))
    fig.colorbar(m, ax=axs[1, 1])

    # diff = LSTN_pred - LSTN2_real
    diff = LSTN_pred - LST_real
    axs[1, 2].imshow(diff, cmap="plasma")
    # axs[1, 2].set_title("Predicted LSTN2 -\n real LSTN2", fontsize=30)
    axs[1, 2].set_title("Predicted LST -\n real LST", fontsize=30)
    m = cm.ScalarMappable(cmap="plasma")
    m.set_clim(np.amin(diff), np.amax(diff))
    fig.colorbar(m, ax=axs[1, 2])

    diff2 = diff ** 2
    axs[1, 3].imshow(diff2, cmap="plasma")
    axs[1, 3].set_title("$L2$ error for LSTN2", fontsize=30)
    m = cm.ScalarMappable(cmap="plasma")
    m.set_clim(np.amin(diff2), np.amax(diff2))
    fig.colorbar(m, ax=axs[1, 3])

    fig.savefig(os.path.join(destination_dir, f"{image_name}.RESULTS.png"))
    fig.clf()


if __name__ == "__main__":
    model_weights = torch.load("saves/reg_LSTN2_model.epoch79.t7")["state"]
    cGAN = ConditionalGAN(
        classes=["LSTN"],
        channels=["NDVI", "NDBI", "NDWI"],
        dis_dropout=0,
        gen_dropout=0,
        no_discriminator=True,
        sigmoid_channels=[False],
        generator_class=None,  # Set in test time
        generator_params=None,  # Set in test time
    )
    cGAN.eval()
    cGAN.generator.eval()
    cGAN.load_state_dict(model_weights)

    image_ids = glob("../data_source/LONDON_DATASET/*NDVI.tif")
    image_ids = [".".join(a.split(".")[:-2]) for a in image_ids]
