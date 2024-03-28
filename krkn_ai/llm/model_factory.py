import importlib

from krkn_ai.abc.ai_model import AIModel


class ModelFactory:

    def get_instance(
        self,
        ai_model_class_name: str,
        ai_model_package: str,
        ai_endpoint: str,
        ai_model_name: str,
    ) -> AIModel:
        try:
            module = importlib.import_module(ai_model_package)
            klass = getattr(module, ai_model_class_name)
            obj = klass(ai_endpoint, ai_model_name)
            if not isinstance(obj, AIModel):
                raise TypeError(
                    f"{ai_model_class_name} does not implement AIModel Abstract class"
                )
            return obj
        except AttributeError as e:
            raise AttributeError(
                f"{ai_model_class_name} AI Model not found in package {ai_model_package}"
            )
