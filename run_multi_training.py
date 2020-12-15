#    Copyright 2020 Division of Medical Image Computing, German Cancer Research Center (DKFZ), Heidelberg, Germany
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.


import argparse
from batchgenerators.utilities.file_and_folder_operations import *
from nnunet.run.default_configuration import get_default_configuration_with_multiTask
from nnunet.paths import default_plans_identifier
from nnunet.training.cascade_stuff.predict_next_stage import predict_next_stage
from nnunet.training.network_training.nnUNetTrainer import nnUNetTrainer
from nnunet.training.network_training.nnUNetTrainerCascadeFullRes import nnUNetTrainerCascadeFullRes
from nnunet.training.network_training.nnUNetTrainerV2_CascadeFullRes import nnUNetTrainerV2CascadeFullRes
from nnunet.utilities.task_name_id_conversion import convert_id_to_task_name
from nnunet.paths import *
from nnunet.training.network_training.nnUNetMultiTrainierV2 import nnUNetMultiTrainerV2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("gpu", help='0, 1, ..., 5 or \'all\'') 
    parser.add_argument("-val", "--validation_only", help="use this if you want to only run the validation",
                        action="store_true")
    parser.add_argument("-c", "--continue_training", help="use this if you want to continue a training",
                        action="store_true")
    parser.add_argument("-p", help="plans identifier. Only change this if you created a custom experiment planner",
                        default=default_plans_identifier, required=False)
    parser.add_argument("--use_compressed_data", default=False, action="store_true",
                        help="If you set use_compressed_data, the training cases will not be decompressed. Reading compressed data "
                             "is much more CPU and RAM intensive and should only be used if you know what you are "
                             "doing", required=False)
    parser.add_argument("--deterministic",
                        help="Makes training deterministic, but reduces training speed substantially. I (Fabian) think "
                             "this is not necessary. Deterministic training will make you overfit to some random seed. "
                             "Don't use that.",
                        required=False, default=False, action="store_true")
    parser.add_argument("--npz", required=False, default=False, action="store_true", help="if set then nnUNet will "
                                                                                          "export npz files of "
                                                                                          "predicted segmentations "
                                                                                          "in the validation as well. "
                                                                                          "This is needed to run the "
                                                                                          "ensembling step so unless "
                                                                                          "you are developing nnUNet "
                                                                                          "you should enable this")
    parser.add_argument("--find_lr", required=False, default=False, action="store_true",
                        help="not used here, just for fun")
    parser.add_argument("--valbest", required=False, default=False, action="store_true",
                        help="hands off. This is not intended to be used")
    parser.add_argument("--fp32", required=False, default=False, action="store_true",
                        help="disable mixed precision training and run old school fp32")
    parser.add_argument("--val_folder", required=False, default="validation_raw",
                        help="name of the validation folder. No need to use this for most people")
    parser.add_argument("--interp_order", required=False, default=3, type=int,
                        help="order of interpolation for segmentations. Testing purpose only. Hands off")
    parser.add_argument("--interp_order_z", required=False, default=0, type=int,
                        help="order of interpolation along z if z is resampled separately. Testing purpose only. "
                             "Hands off")
    parser.add_argument("--force_separate_z", required=False, default="None", type=str,
                        help="force_separate_z resampling. Can be None, True or False. Testing purpose only. Hands off")

    args = parser.parse_args()


    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
    tasks = ["100", "101", "102", "103", "104"]
    # tasks = ["100"]
    # fold = args.fold
    fold = "4"
    # network = args.network
    network = "3d_fullres"
    network_trainer = "nnUNetMultiTrainerV2"
    validation_only = args.validation_only
    plans_identifier = args.p
    find_lr = args.find_lr

    use_compressed_data = args.use_compressed_data
    decompress_data = not use_compressed_data

    deterministic = args.deterministic
    valbest = args.valbest

    fp32 = args.fp32
    run_mixed_precision = not fp32

    val_folder = args.val_folder
    # val_folder = "mk_validation"   #temp_validation
    interp_order = args.interp_order
    interp_order_z = args.interp_order_z
    force_separate_z = args.force_separate_z
    
    classes_dict = {}
    for i, task in enumerate(tasks):
        if not task.startswith("Task"):
            task_id = int(task)
            task = convert_id_to_task_name(task_id)
        tasks[i] = task

        json_file = join(preprocessing_output_dir,task, "dataset.json")
        classes = []
        with open(json_file) as jsn:
            d = json.load(jsn)
            tags = d['labels']
            for i in tags:
                if not int(i) == 0:#bkg not in tag
                    classes.append(tags[i])
            classes_dict[task] = classes
    # print("task:",tasks)# ['Task100_MALB', 'Task101_Liver', 'Task102_Spleen', 'Task103_Pancreas', 'Task104_KiTS']
    # print("classes_dict", classes_dict)#{'Task100_MALB': ['Liver', 'Spleen', 'Pancreas', 'LeftKidney', 'RightKidney'],...}
    if fold == 'all':
        pass
    else:
        fold = int(fold)

    if force_separate_z == "None":
        force_separate_z = None
    elif force_separate_z == "False":
        force_separate_z = False
    elif force_separate_z == "True":
        force_separate_z = True
    else:
        raise ValueError(
            "force_separate_z must be None, True or False. Given: %s" % force_separate_z)

    plans_file, output_folder_names, dataset_directorys, batch_dice, stage, \
        trainer_class = get_default_configuration_with_multiTask(
            network, tasks, network_trainer, plans_identifier)
    
    if trainer_class is None:
        raise RuntimeError(
            "Could not find trainer class in nnunet.training.network_training")

    if network == "3d_cascade_fullres":
        assert issubclass(trainer_class, (nnUNetTrainerCascadeFullRes, nnUNetTrainerV2CascadeFullRes)), \
            "If running 3d_cascade_fullres then your " \
            "trainer class must be derived from " \
            "nnUNetTrainerCascadeFullRes"
    else:
        assert issubclass(trainer_class,
                          nnUNetTrainer), "network_trainer was found but is not derived from nnUNetMultiTrainer"

    trainer = trainer_class(plans_file, fold,tasks,tags=classes_dict, output_folder_dict=output_folder_names, dataset_directory_dict=dataset_directorys,
                            batch_dice=batch_dice, stage=0, unpack_data=decompress_data,
                            deterministic=deterministic,
                            fp16=run_mixed_precision)
                      

    trainer.initialize(not validation_only)

    if find_lr:
        trainer.find_lr()
    else:
        if not validation_only:
            if args.continue_training:
                trainer.load_latest_checkpoint()
            trainer.run_training() #training
        else:
            if valbest:
                trainer.load_best_checkpoint(train=False)
            else:
                trainer.load_latest_checkpoint(train=False)

        trainer.network.eval()

        # predict validation
        for task in tasks:
            print(f"test task: {task}")
            trainer.validate_specific_data(task,save_softmax=args.npz, validation_folder_name=val_folder, force_separate_z=force_separate_z,overwrite=True,
                            interpolation_order=interp_order, interpolation_order_z=interp_order_z)
        

if __name__ == "__main__":
    main()
