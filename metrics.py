from imports import *

def dice_coef(preds, labels):
    smooth = 1.0
    preds = preds.cpu().detach()
    labels = labels.cpu().detach()

    preds_flat = preds.view(-1)
    labels_flat = labels.view(-1)
    intersection = (preds_flat * labels_flat).sum()

    return (2.0 * intersection + smooth) / (
        preds_flat.sum() + labels_flat.sum() + smooth
    )

class DiceCoefficient(nn.Module):
    def __init__(self, **kwargs):
        """
        Beta is on positive side, so a higher beta stops false negatives more
        """
        super(DiceCoefficient, self).__init__()

    def forward(self, preds: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        return dice_coef(preds, labels)


def multiply_by_class_weights(class_weights, class_losses):
    if type(class_weights) == type(None):
      class_weights = torch.Tensor([1 for _ in range(len(class_losses))])
    else:
      class_weights = torch.tensor(class_weights).float()
    class_weights = class_weights/torch.norm(class_weights, dim=0)
  
    class_losses = class_losses.reshape(-1)

    try:
        return torch.dot(class_losses, class_weights.double())
    except RuntimeError:
        return torch.dot(class_losses, class_weights.float())



def cross_entropy(y, t, beta):
    # y is preds, t is labels as per Bishop
    # Normalise ratio
    mag = np.sqrt(beta ** 2 + 1)
    beta_ = beta / mag
    alpha_ = 1 / mag
    return beta_ * t * torch.log2(y) + alpha_ * (1 - t) * torch.log2(1 - y)


def perPixelCrossEntropy(preds, labels, class_weights, beta):
    size = torch.prod(torch.tensor(labels.shape)).float()
    assert preds.shape == labels.shape
    class_losses = -(1 / size) * torch.sum(
        # Sum over everything but classes
        cross_entropy(preds, labels, beta), dim=(-2, -1)
    )
    return multiply_by_class_weights(class_weights, class_losses)


def jaccardIndex(preds, labels, class_weights=None):
    size = torch.prod(torch.tensor(labels.shape)).float()
    assert preds.shape == labels.shape
    class_indices = (1 / size) * torch.sum(
        preds * labels / (preds + labels - labels * preds + 1e-10), dim=(-2, -1)
    )
    return multiply_by_class_weights(class_weights, class_indices)


def ternausLossfunc(preds, labels, l=1, beta=1, HWs=None, JWs=None):
    # Derived from https://arxiv.org/abs/1801.05746
    H = perPixelCrossEntropy(preds, labels, HWs, beta)
    J = jaccardIndex(preds, labels, JWs)
    return H - l * torch.log(J + 1e-10)


class TernausLossFunc(nn.Module):
    def __init__(self, **kwargs):
        """
        Beta is on positive side, so a higher beta stops false negatives more
        """
        super(TernausLossFunc, self).__init__()
        self.l = kwargs.get("l",1)
        self.beta = kwargs.get("beta", 1)
        self.HWs = kwargs.get("HWs")
        self.JWs = kwargs.get("JWs")

    def forward(self, preds: torch.Tensor, labels: torch.Tensor, reorder = False) -> torch.Tensor:
        if reorder:
          labels = labels.permute(0, 3, 1, 2)
        return ternausLossfunc(preds, labels, self.l, self.beta, self.HWs, self.JWs)


class TargettedRegressionClassification(nn.Module):
  # This provides a classification loss to the segmentation layer, 
  # and a regression loss to the continuous layer weighted by the segmentation

  def __init__(self, **kwargs):
      super(TargettedRegressionClassification, self).__init__()

      # Which channel of the inputted images is cls and reg
      self.cls_layer = kwargs["cls_layer"]
      self.reg_layer = kwargs["reg_layer"]

      self.reg_loss_func = kwargs["reg_loss_func"]
      self.cls_loss_func = kwargs["cls_loss_func"]

      self.cls_lambda = kwargs["cls_lambda"]
      self.reg_lambda = kwargs["reg_lambda"]

  
  def forward(self, preds, labels):
      reg_preds = preds[self.reg_layer]
      cls_preds = preds[self.cls_layer]
      mul_preds = cls_preds*reg_preds

      reg_labels = labels[self.reg_layer]
      cls_labels = labels[self.cls_layer]

      reg_loss = self.reg_loss_func(mul_preds, reg_labels)
      cls_loss = self.cls_loss_func(cls_preds, cls_labels)

      comparison_loss = (
          self.reg_lambda*reg_loss +
          self.cls_lambda*cls_loss
      )

      return comparison_loss


class TargettedTernausAndMSE(TargettedRegressionClassification):
  # A targetted loss that uses Ternaus for cls and MSE for reg

  def __init__(self, **kwargs):
    
    kwargs["reg_loss_func"] = TernausLossFunc(**kwargs)
    kwargs["cls_loss_func"] = nn.MSELoss()
    super(TargettedTernausAndMSE, self).__init__(**kwargs)


