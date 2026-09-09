from dataclasses import dataclass

@dataclass
class LabelData:
    sku: str
    description: str
    address: str
    quantity: int = 1

class PrinterService:
    """
    Adaptador de impressão.
    Substituir internamente pela mesma rotina usada no projeto CS.
    O restante do CHAPA ID não precisa mudar.
    """

    def status(self):
        return {"online": True, "mode": "adapter-ready", "message": "Adaptador aguardando rotina do projeto CS"}

    def print_label(self, data: LabelData):
        # TODO: inserir aqui a mesma chamada do equipamento/driver do projeto CS.
        return {
            "ok": True,
            "queued": data.quantity,
            "sku": data.sku,
            "message": "Etiqueta enviada para a fila de impressão (modo demonstração)."
        }

printer = PrinterService()
