﻿from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, F, Q
from django.shortcuts import render
from django.views.generic import TemplateView


from common.views import AbsTargetSelection
from common.definitions import STRUCTURAL_RULES, STRUCTURAL_SWITCHES
from common.selection import Selection
Alignment = getattr(__import__(
    'common.alignment_' + settings.SITE_NAME,
    fromlist=['Alignment']
    ), 'Alignment')

from common.sequence_signature import SequenceSignature, SignatureMatch

from alignment.functions import get_proteins_from_selection
from construct.views import create_structural_rule_trees, ConstructMutation
from contactnetwork.models import InteractingResiduePair
from interaction.models import ResidueFragmentInteraction
from mutation.models import MutationExperiment
from mutational_landscape.models import NaturalMutations, CancerMutations, DiseaseMutations, PTMs, NHSPrescribings
from protein.models import ProteinSegment, Protein, ProteinGProtein, ProteinGProteinPair
from residue.models import Residue,ResidueNumberingScheme, ResiduePositionSet, ResidueSet

from collections import OrderedDict

import re
import time

class TargetSelection(AbsTargetSelection):
    pass

class ResidueTablesSelection(AbsTargetSelection):

    # Left panel
    step = 1
    number_of_steps = 2
    docs = 'generic_numbering.html'

    description = 'Select receptors to index by searching or browsing in the middle column. You can select entire' \
        + ' receptor families and/or individual receptors.\n\nSelected receptors will appear in the right column,' \
        + ' where you can edit the list.\n\nSelect which numbering schemes to use in the middle column.\n\nOnce you' \
        + ' have selected all your receptors, click the green button.'


    # Middle section
    numbering_schemes = True


    # Buttons
    buttons = {
        'continue' : {
            'label' : 'Show residue numbers',
            'url' : '/residue/residuetabledisplay',
            'color' : 'success',
            }
        }


class ResidueTablesDisplay(TemplateView):
    """
    A class rendering the residue numbering table.
    """
    template_name = 'residue_table.html'

    def get_context_data(self, **kwargs):
        """
        Get the selection data (proteins and numbering schemes) and prepare it for display.
        """
        context = super().get_context_data(**kwargs)

        # get the user selection from session
        simple_selection = self.request.session.get('selection', False)

         # local protein list
        proteins = []

        # flatten the selection into individual proteins
        for target in simple_selection.targets:
            if target.type == 'protein':
                proteins.append(target.item)
            elif target.type == 'family':
                # species filter
                species_list = []
                for species in simple_selection.species:
                    species_list.append(species.item)

                # annotation filter
                protein_source_list = []
                for protein_source in simple_selection.annotation:
                    protein_source_list.append(protein_source.item)

                if species_list:
                    family_proteins = Protein.objects.filter(family__slug__startswith=target.item.slug,
                        species__in=(species_list),
                        source__in=(protein_source_list)).select_related('residue_numbering_scheme', 'species')
                else:
                    family_proteins = Protein.objects.filter(family__slug__startswith=target.item.slug,
                        source__in=(protein_source_list)).select_related('residue_numbering_scheme', 'species')

                for fp in family_proteins:
                    proteins.append(fp)

            longest_name = 0
            species_list = {}
            for protein in proteins:
                if protein.species.common_name not in species_list:
                    if len(protein.species.common_name)>10 and len(protein.species.common_name.split())>1:
                        name = protein.species.common_name.split()[0][0]+". "+" ".join(protein.species.common_name.split()[1:])
                        if len(" ".join(protein.species.common_name.split()[1:]))>11:
                            name = protein.species.common_name.split()[0][0]+". "+" ".join(protein.species.common_name.split()[1:])[:8]+".."
                    else:
                        name = protein.species.common_name
                    species_list[protein.species.common_name] = name
                else:
                    name = species_list[protein.species.common_name]

                if len(re.sub('<[^>]*>', '', protein.name)+" "+name)>longest_name:
                    longest_name = len(re.sub('<[^>]*>', '', protein.name)+" "+name)

        # get the selection from session
        selection = Selection()
        if simple_selection:
             selection.importer(simple_selection)
        # # extract numbering schemes and proteins
        numbering_schemes = [x.item for x in selection.numbering_schemes]

        # # get the helices (TMs only at first)
        segments = ProteinSegment.objects.filter(category='helix', proteinfamily='GPCR')

        if ResidueNumberingScheme.objects.get(slug=settings.DEFAULT_NUMBERING_SCHEME) in numbering_schemes:
            default_scheme = ResidueNumberingScheme.objects.get(slug=settings.DEFAULT_NUMBERING_SCHEME)
        else:
            default_scheme = numbering_schemes[0]

        # prepare the dictionary
        # each helix has a dictionary of positions
        # default_generic_number or first scheme on the list is the key
        # value is a dictionary of other gn positions and residues from selected proteins
        data = OrderedDict()
        for segment in segments:
            data[segment.slug] = OrderedDict()
            residues = Residue.objects.filter(protein_segment=segment, protein_conformation__protein__in=proteins).prefetch_related('protein_conformation__protein', 'protein_conformation__state', 'protein_segment',
                'generic_number__scheme', 'display_generic_number__scheme', 'alternative_generic_numbers__scheme')
            for scheme in numbering_schemes:
                if scheme == default_scheme and scheme.slug == settings.DEFAULT_NUMBERING_SCHEME:
                    for pos in list(set([x.generic_number.label for x in residues if x.protein_segment == segment])):
                        data[segment.slug][pos] = {scheme.slug : pos, 'seq' : ['-']*len(proteins)}
                elif scheme == default_scheme:
                    for pos in list(set([x.generic_number.label for x in residues if x.protein_segment == segment])):
                            data[segment.slug][pos] = {scheme.slug : pos, 'seq' : ['-']*len(proteins)}

            for residue in residues:
                alternatives = residue.alternative_generic_numbers.all()
                pos = residue.generic_number
                for alternative in alternatives:
                    scheme = alternative.scheme
                    if default_scheme.slug == settings.DEFAULT_NUMBERING_SCHEME:
                        pos = residue.generic_number
                        if scheme == pos.scheme:
                            data[segment.slug][pos.label]['seq'][proteins.index(residue.protein_conformation.protein)] = str(residue)
                        else:
                            if scheme.slug not in data[segment.slug][pos.label].keys():
                                data[segment.slug][pos.label][scheme.slug] = alternative.label
                            if alternative.label not in data[segment.slug][pos.label][scheme.slug]:
                                data[segment.slug][pos.label][scheme.slug] += " "+alternative.label
                            data[segment.slug][pos.label]['seq'][proteins.index(residue.protein_conformation.protein)] = str(residue)
                    else:
                        if scheme.slug not in data[segment.slug][pos.label].keys():
                            data[segment.slug][pos.label][scheme.slug] = alternative.label
                        if alternative.label not in data[segment.slug][pos.label][scheme.slug]:
                            data[segment.slug][pos.label][scheme.slug] += " "+alternative.label
                        data[segment.slug][pos.label]['seq'][proteins.index(residue.protein_conformation.protein)] = str(residue)

        # Preparing the dictionary of list of lists. Dealing with tripple nested dictionary in django templates is a nightmare
        flattened_data = OrderedDict.fromkeys([x.slug for x in segments], [])
        print(flattened_data)
        for s in iter(flattened_data):
            flattened_data[s] = [[data[s][x][y.slug] for y in numbering_schemes]+data[s][x]['seq'] for x in sorted(data[s])]

        context['header'] = zip([x.short_name for x in numbering_schemes] + [x.name+" "+species_list[x.species.common_name] for x in proteins], [x.name for x in numbering_schemes] + [x.name for x in proteins],[x.name for x in numbering_schemes] + [x.entry_name for x in proteins])
        context['segments'] = [x.slug for x in segments]
        context['data'] = flattened_data
        context['number_of_schemes'] = len(numbering_schemes)
        context['longest_name'] = {'div' : longest_name*2, 'height': longest_name*2+80}

        return context

class ResidueFunctionBrowser(TemplateView):
    """
    Per generic position summary of functional information
    """
    template_name = 'residue_function_browser.html'

    def get_context_data (self, **kwargs):
        # setup caches
        cache_name = "RFB"
        rfb_panel = cache.get(cache_name)
#        rfb_panel = None
        if rfb_panel == None:
            rfb_panel = {}

            # Signatures
            rfb_panel["signatures"] = {}

            # Grab relevant segments
            segments = list(ProteinSegment.objects.filter(proteinfamily='GPCR'))

            # Grab High/Low CA GPCRs (class A)
            print("Grabbing CA sets")
            high_ca = ["5ht2c_human", "acm4_human", "drd1_human", "fpr1_human", "ghsr_human", "cnr1_human", "aa1r_human", "gpr6_human", "gpr17_human", "gpr87_human"]
            low_ca = ["agtr1_human", "ednrb_human", "gnrhr_human", "acthr_human", "v2r_human", "gp141_human", "gp182_human"]

            # Signature High vs Low CA
            high_ca_gpcrs = Protein.objects.filter(entry_name__in=high_ca).select_related('residue_numbering_scheme', 'species')
            low_ca_gpcrs = Protein.objects.filter(entry_name__in=low_ca).select_related('residue_numbering_scheme', 'species')

            print("Grabbing CA sets - HIGH vs LOW")
            signature = SequenceSignature()
            signature.setup_alignments(segments, high_ca_gpcrs, low_ca_gpcrs)
            signature.calculate_signature()
            rfb_panel["signatures"]["cah"] = signature.signature
            rfb_panel["signatures"]["cah_positions"] = signature.common_gn

            print("Grabbing CA sets - LOW vs HIGH")
            signature = SequenceSignature()
            signature.setup_alignments(segments, low_ca_gpcrs, high_ca_gpcrs)
            signature.calculate_signature()
            rfb_panel["signatures"]["cal"] = signature.signature
            rfb_panel["signatures"]["cal_positions"] = signature.common_gn

            # Grab Gi/Gs/Gq/GI12 GPCR sets (class A)
            print(str(time.time()) + " Grabbing G-protein sets")

            human_class_a_gpcrs = Protein.objects.filter(species_id=1, sequence_type_id=1, family__slug__startswith='001').distinct().prefetch_related('proteingprotein_set', 'residue_numbering_scheme')
            gs  = list(human_class_a_gpcrs.filter(proteingprotein__slug="100_000_001"))
            gio = list(human_class_a_gpcrs.filter(proteingprotein__slug="100_000_002"))
            gq  = list(human_class_a_gpcrs.filter(proteingprotein__slug="100_000_003"))
            g12 = list(human_class_a_gpcrs.filter(proteingprotein__slug="100_000_004"))
            all = set(gs + gio + gq + g12)

            # Create sequence signatures for the G-protein sets
            print(str(time.time()) + " Signature")
            for gprotein in ["gs", "gio", "gq", "g12"]:
                print("Processing " + gprotein)
                # Signature receptors specific for a G-protein vs all others
                signature = SequenceSignature()
                signature.setup_alignments(segments, locals()[gprotein], all.difference(locals()[gprotein]))
                signature.calculate_signature()
                rfb_panel["signatures"][gprotein] = signature.signature
                rfb_panel["signatures"][gprotein + "_positions"] = signature.common_gn

                print("Done with this set")

            # Add class A alignment features
            print(str(time.time()) + " class A signatures")

            signature = SequenceSignature()
            signature.setup_alignments(segments, human_class_a_gpcrs, [list(human_class_a_gpcrs)[0]])
            signature.calculate_signature()
            rfb_panel["class_a_positions"] = signature.common_gn
            rfb_panel["class_a_aa"] = signature.aln_pos.consensus
            rfb_panel["class_a_prop"] = signature.features_consensus_pos

            # Add X-ray ligand contacts
            # Optionally include the curation with the following filter: structure_ligand_pair__annotated=True
            class_a_interactions = ResidueFragmentInteraction.objects.filter(
                structure_ligand_pair__structure__protein_conformation__protein__family__slug__startswith="001").exclude(interaction_type__type='hidden')\
                .values("rotamer__residue__generic_number__label").annotate(unique_receptors=Count("rotamer__residue__protein_conformation__protein__family_id", distinct=True))

            rfb_panel["ligand_binding"] = {entry["rotamer__residue__generic_number__label"] : entry["unique_receptors"] for entry in list(class_a_interactions)}

            # Add genetic variations
            all_nat_muts = NaturalMutations.objects.filter(protein__family__slug__startswith="001").values("residue__generic_number__label").annotate(unique_receptors=Count("protein__family_id", distinct=True))
            rfb_panel["natural_mutations"] = {entry["residue__generic_number__label"] : entry["unique_receptors"] for entry in list(all_nat_muts)}
    #        print(natural_mutations)

            # Add PTMs
            all_ptms = PTMs.objects.filter(protein__family__slug__startswith="001").values("residue__generic_number__label").annotate(unique_receptors=Count("protein__family_id", distinct=True))
            rfb_panel["ptms"] = {entry["residue__generic_number__label"] : entry["unique_receptors"] for entry in list(all_ptms)}

            # Thermostabilizing
            all_thermo = ConstructMutation.objects.filter(construct__protein__family__slug__startswith="001", effects__slug='thermostabilising')\
                        .values("residue__generic_number__label").annotate(unique_receptors=Count("construct__protein__family_id", distinct=True))
            rfb_panel["thermo_mutations"] = {entry["residue__generic_number__label"] : entry["unique_receptors"] for entry in list(all_thermo)}


            # Class A ligand mutations >5 fold effect - count unique receptors
            all_ligand_mutations = MutationExperiment.objects.filter(Q(foldchange__gte = 5) | Q(foldchange__lte = -5), protein__family__slug__startswith="001")\
                            .values("residue__generic_number__label").annotate(unique_receptors=Count("protein__family_id", distinct=True))
            rfb_panel["ligand_mutations"] = {entry["residue__generic_number__label"] : entry["unique_receptors"] for entry in list(all_ligand_mutations)}

            # Class A mutations with >30% increase/decrease basal activity
            all_basal_mutations = MutationExperiment.objects.filter(Q(opt_basal_activity__gte = 130) | Q(opt_basal_activity__lte = 70), protein__family__slug__startswith="001")\
                            .values("residue__generic_number__label").annotate(unique_receptors=Count("protein__family_id", distinct=True))
            rfb_panel["basal_mutations"] = {entry["residue__generic_number__label"] : entry["unique_receptors"] for entry in list(all_basal_mutations)}

            # Intrasegment contacts
            all_contacts = InteractingResiduePair.objects.filter(~Q(res1__protein_segment_id = F('res2__protein_segment_id')), referenced_structure__protein_conformation__protein__family__slug__startswith="001")\
                            .values("res1__generic_number__label").annotate(unique_receptors=Count("referenced_structure__protein_conformation__protein__family_id", distinct=True))
            rfb_panel["intrasegment_contacts"] = {entry["res1__generic_number__label"] : entry["unique_receptors"] for entry in list(all_contacts)}


            # Active/Inactive contacts
            all_active_contacts = InteractingResiduePair.objects.filter(~Q(res2__generic_number__label = None), ~Q(res1__generic_number__label = None),\
                    referenced_structure__state__slug = "active", referenced_structure__protein_conformation__protein__family__slug__startswith="001")\
                    .values("res1__generic_number__label", "res2__generic_number__label")

            # OPTIMIZE
            active_contacts = {}
            for entry in list(all_active_contacts):
                if entry["res1__generic_number__label"] not in active_contacts:
                    active_contacts[entry["res1__generic_number__label"]] = set()
                active_contacts[entry["res1__generic_number__label"]].update([entry["res2__generic_number__label"]])
            rfb_panel["active_contacts"] = active_contacts

            all_inactive_contacts = InteractingResiduePair.objects.filter(~Q(res2__generic_number__label = None), ~Q(res1__generic_number__label = None),\
                    referenced_structure__state__slug = "inactive", referenced_structure__protein_conformation__protein__family__slug__startswith="001")\
                    .values("res1__generic_number__label", "res2__generic_number__label")

            # OPTIMIZE
            inactive_contacts = {}
            for entry in list(all_inactive_contacts):
                if entry["res1__generic_number__label"] not in inactive_contacts:
                        inactive_contacts[entry["res1__generic_number__label"]] = set()
                inactive_contacts[entry["res1__generic_number__label"]].update([entry["res2__generic_number__label"]])
            rfb_panel["inactive_contacts"] = inactive_contacts

            cache.set(cache_name, rfb_panel, 3600*24*7) # cache a week

        # Other rules
#        structural_rule_tree = create_structural_rule_trees(STRUCTURAL_RULES)
#        print(structural_rule_tree)

        ######## CREATE REFERENCE sets (or use structural rules)

        ## MICROSWITCHES
        ms_labels = [residue.label for residue in ResiduePositionSet.objects.get(name="Microswitches").residue_position.all()]

        ## SODIUM POCKET
        sp_labels = [residue.label for residue in ResiduePositionSet.objects.get(name="Sodium pocket").residue_position.all()]

        ## ROTAMER SWITCHES
        rotamer_labels = []
        for entry in STRUCTURAL_SWITCHES["A"]:
            if entry["Rotamer Switch"] != "-":
                rotamer_labels.append(entry["AA1 Pos"])
                rotamer_labels.append(entry["AA2 Pos"])


        ## G PROTEIN INTERACTION POSITIONS
#        gprotein_labels = [residue.label for residue in ResiduePositionSet.objects.get(name="Signalling protein pocket").residue_position.all()]
        # Class A G-protein X-ray contacts
        # TODO: replace with automatically generated sets from X-rays stored in database
        gprotein_labels = {"1.60x60": {"001_006_001_001", " 001_006_001_002"},
                            "12.48x48": {"001_001_003_008", " 001_006_001_001", " 001_006_001_002", " 001_009_001_001"},
                            "12.49x49": {"001_001_003_008", " 001_006_001_002"},
                            "12.51x51": {"001_006_001_002"},
                            "2.37x37": {"001_006_001_001"},
                            "2.39x39": {"001_002_022_003"},
                            "2.40x40": {"001_006_001_001"},
                            "3.49x49": {"001_001_003_008", " 001_002_022_003"},
                            "3.50x50": {"001_001_001_002", " 001_001_003_008", " 001_002_022_003", " 001_006_001_001", " 001_006_001_002", " 001_009_001_001"},
                            "3.53x53": {"001_001_001_002", " 001_001_003_008", " 001_002_022_003", " 001_006_001_001", " 001_006_001_002"},
                            "3.54x54": {"001_001_001_002", " 001_001_003_008", " 001_002_022_003", " 001_006_001_001", " 001_006_001_002", " 001_009_001_001"},
                            "3.55x55": {"001_001_003_008", " 001_006_001_002"},
                            "3.56x56": {"001_006_001_002", " 001_009_001_001"},
                            "34.50x50": {"001_001_001_002", " 001_001_003_008", " 001_002_022_003", " 001_006_001_001", " 001_006_001_002"},
                            "34.51x51": {"001_001_001_002", " 001_001_003_008", " 001_002_022_003", " 001_006_001_001", " 001_006_001_002"},
                            "34.52x52": {"001_001_003_008", " 001_002_022_003", " 001_006_001_002"},
                            "34.53x53": {"001_001_003_008", " 001_006_001_002"},
                            "34.54x54": {"001_001_003_008", " 001_002_022_003", " 001_006_001_002"},
                            "34.55x55": {"001_001_003_008", " 001_002_022_003", " 001_006_001_002", " 001_009_001_001"},
                            "34.57x57": {"001_001_001_002", " 001_002_022_003"},
                            "4.40x40": {"001_002_022_003"},
                            "5.61x61": {"001_001_001_002", " 001_001_003_008", " 001_002_022_003", " 001_006_001_001", " 001_006_001_002"},
                            "5.64x64": {"001_001_003_008", " 001_002_022_003", " 001_006_001_002"},
                            "5.65x65": {"001_001_001_002", " 001_001_003_008", " 001_002_022_003", " 001_006_001_001", " 001_006_001_002"},
                            "5.67x67": {"001_001_003_008"},
                            "5.68x68": {"001_001_001_002", " 001_001_003_008", " 001_002_022_003", " 001_006_001_001", " 001_006_001_002"},
                            "5.69x69": {"001_001_001_002", " 001_001_003_008", " 001_006_001_001", " 001_006_001_002"},
                            "5.71x71": {"001_001_003_008", " 001_006_001_001", " 001_006_001_002"},
                            "5.72x72": {"001_001_003_008", " 001_006_001_002", " 001_009_001_001"},
                            "5.74x74": {"001_001_003_008"},
                            "6.23x23": {"001_002_022_003"},
                            "6.24x24": {"001_009_001_001"},
                            "6.25x25": {"001_002_022_003", " 001_006_001_001", " 001_009_001_001"},
                            "6.26x26": {"001_002_022_003", " 001_009_001_001"},
                            "6.28x28": {"001_009_001_001"},
                            "6.29x29": {"001_001_001_002", " 001_006_001_001", " 001_006_001_002", " 001_009_001_001"},
                            "6.32x32": {"001_001_001_002", " 001_002_022_003", " 001_006_001_001", " 001_006_001_002", " 001_009_001_001"},
                            "6.33x33": {"001_001_001_002", " 001_001_003_008", " 001_002_022_003", " 001_006_001_001", " 001_006_001_002", " 001_009_001_001"},
                            "6.36x36": {"001_001_001_002", " 001_001_003_008", " 001_002_022_003", " 001_006_001_002", " 001_009_001_001"},
                            "6.37x37": {"001_001_001_002", " 001_001_003_008", " 001_006_001_001", " 001_006_001_002"},
                            "7.56x56": {"001_001_001_002", " 001_006_001_001", " 001_006_001_002", " 001_009_001_001"},
                            "8.47x47": {"001_001_001_002", " 001_002_022_003", " 001_006_001_001", " 001_009_001_001"},
                            "8.48x48": {"001_002_022_003", " 001_006_001_002", " 001_009_001_001"},
                            "8.49x49": {"001_006_001_001", " 001_006_001_002"},
                            "8.51x51": {"001_006_001_002"},
                            "8.56x56": {"001_006_001_001"}}

        # TODO: replace with automatically generated sets from X-rays stored in database
        # Class A Arrestin X-ray contacts
        arrestin_labels = {"12.49x49": {"001_009_001_001"},
                            "2.37x37": {"001_009_001_001"},
                            "2.38x38": {"001_009_001_001"},
                            "2.39x39": {"001_009_001_001"},
                            "2.40x40": {"001_009_001_001"},
                            "2.43x43": {"001_009_001_001"},
                            "3.50x50": {"001_009_001_001"},
                            "3.54x54": {"001_009_001_001"},
                            "3.55x55": {"001_009_001_001"},
                            "3.56x56": {"001_009_001_001"},
                            "34.50x50": {"001_009_001_001"},
                            "34.51x51": {"001_009_001_001"},
                            "34.53x53": {"001_009_001_001"},
                            "34.54x54": {"001_009_001_001"},
                            "34.55x55": {"001_009_001_001"},
                            "34.56x56": {"001_009_001_001"},
                            "4.38x38": {"001_009_001_001"},
                            "5.61x61": {"001_009_001_001"},
                            "5.64x64": {"001_009_001_001"},
                            "5.68x68": {"001_009_001_001"},
                            "5.69x69": {"001_009_001_001"},
                            "5.71x71": {"001_009_001_001"},
                            "5.72x72": {"001_009_001_001"},
                            "6.24x24": {"001_009_001_001"},
                            "6.25x25": {"001_009_001_001"},
                            "6.26x26": {"001_009_001_001"},
                            "6.28x28": {"001_009_001_001"},
                            "6.29x29": {"001_009_001_001"},
                            "6.32x32": {"001_009_001_001"},
                            "6.33x33": {"001_009_001_001"},
                            "6.36x36": {"001_009_001_001"},
                            "6.37x37": {"001_009_001_001"},
                            "6.40x40": {"001_009_001_001"},
                            "8.47x47": {"001_009_001_001"},
                            "8.48x48": {"001_009_001_001"},
                            "8.49x49": {"001_009_001_001"},
                            "8.50x50": {"001_009_001_001"}}

        # Positions in center of membrane selected using 4BVN together with OPM membrane positioning
        # Reference: ['1x44', '2x52', '3x36', '4x54', '5x46', '6x48', '7x43']
        mid_membrane = {'TM1': 44,'TM2': 52,'TM3': 36,'TM4': 54,'TM5': 46, 'TM6': 48, 'TM7': 43}

        # Positions within membrane layer selected using 4BVN together with OPM membrane positioning
        core_membrane = {'TM1': [33, 55],'TM2': [42,65],'TM3': [23,47],'TM4': [43,64],'TM5': [36,59], 'TM6': [37,60], 'TM7': [32,54]}

        # Residue oriented outward of bundle (based on inactive 4BVN and active 3SN6)
        outward_orientation = {
            'TM1' : [29, 30, 33, 34, 36, 37, 38, 40, 41, 44, 45, 48, 51, 52, 54, 55, 58],
            'TM2' : [38, 41, 45, 48, 52, 55, 56, 58, 59, 60, 62, 63, 66],
            'TM3' : [23, 24, 27, 31, 48, 51, 52, 55],
            'TM4' : [40, 41, 43, 44, 47, 48, 50, 51, 52, 54, 55, 58, 59, 62, 63, 81],
            'TM5' : [36, 37, 38, 40, 41, 42, 44, 45, 46, 48, 49, 52, 53, 55, 56, 57, 59, 60, 62, 63, 64, 66, 67, 68, 70, 71, 73, 74],
            'TM6' : [25, 28, 29, 31, 32, 34, 35, 38, 39, 42, 43, 45, 46, 49, 50, 53, 54, 56, 57, 60],
            'TM7' : [33, 34, 35, 37, 40, 41, 43, 44, 48, 51, 52, 54, 55]
        }

        ########

        # prepare context for output
        print(str(time.time()) + " preparing the context")
        context = {"signatures" : []}
        index = 0
        for h, segment in enumerate(rfb_panel["signatures"]["gs_positions"]["gpcrdba"]):
            segment_first = True
            for i, position in enumerate(rfb_panel["signatures"]["gs_positions"]["gpcrdba"][segment]):
                if len(position) <= 5:
                    # To filter segment headers with non-GN numbering
                    if segment_first:
                        context["signatures"].append({"position" : segment})
                        index += 1
                        segment_first = False

                    # Add data
                    context["signatures"].append({})
                    context["signatures"][index]["segment"] = segment
                    context["signatures"][index]["sort"] = index
                    context["signatures"][index]["position"] = position

                    # Normalized position in TM
                    partial_position = int(position.split('x')[1][:2])

                    # RESIDUE PLACEMENT
                    context["signatures"][index]["membane_placement"] = "-"
                    context["signatures"][index]["membane_segment"] = "Extracellular"
                    context["signatures"][index]["residue_orientation"] = "-"
                    if segment in mid_membrane: # TM helix
                        # parse position
                        context["signatures"][index]["membane_placement"] = partial_position - mid_membrane[segment]

                        # negative is toward cytoplasm
                        if segment in ['TM1', 'TM3', 'TM5', 'TM7']: # downwards
                            context["signatures"][index]["membane_placement"] = -1 * context["signatures"][index]["membane_placement"]

                        # Segment selection
                        if partial_position >= core_membrane[segment][0] and partial_position <= core_membrane[segment][1]:
                            context["signatures"][index]["membane_segment"] = "Membrane"
                        elif segment in ['TM1', 'TM3', 'TM5', 'TM7']:
                            if partial_position > core_membrane[segment][1]:
                                context["signatures"][index]["membane_segment"] = "Intracellular"
                        else:
                            if partial_position < core_membrane[segment][0]:
                                context["signatures"][index]["membane_segment"] = "Intracellular"

                        # Orientation
                        if partial_position in outward_orientation[segment]:
                            context["signatures"][index]["residue_orientation"] = "Outward"
                        else:
                            if partial_position > min(outward_orientation[segment]) and partial_position < max(outward_orientation[segment]):
                                context["signatures"][index]["residue_orientation"] = "Inward"
                    # Intracellular segments
                    elif segment in ['ICL1', 'ICL2', 'ICL3', 'TM8', 'C-term']:
                        context["signatures"][index]["membane_segment"] = "Intracellular"

                    # COUNTS: all db results in a singe loop
                    for key in ["ligand_binding", "natural_mutations", "thermo_mutations", "ligand_mutations", "basal_mutations", "intrasegment_contacts", "ptms"]: # Add in future "gprotein_interface", "arrestin_interface"
                        context["signatures"][index][key] = 0
                        if position in rfb_panel[key]:
                            context["signatures"][index][key] = rfb_panel[key][position]

                    # G-protein interface
                    context["signatures"][index]["gprotein_interface"] = 0
                    if position in gprotein_labels:
                        context["signatures"][index]["gprotein_interface"] = len(gprotein_labels[position])

                    # Arrestin interface
                    context["signatures"][index]["arrestin_interface"] = 0
                    if position in arrestin_labels:
                        context["signatures"][index]["arrestin_interface"] = len(arrestin_labels[position])

                    # BINARY

                    # Microswitch
                    context["signatures"][index]["microswitch"] = position in ms_labels

                    # Sodium pocket
                    context["signatures"][index]["sodium"] = position in sp_labels

                    # Rotamer switch
                    context["signatures"][index]["rotamer_switch"] = position in rotamer_labels

                    # contacts
                    context["signatures"][index]["active_contacts"] = False
                    if position in rfb_panel["active_contacts"]:
                        if position in rfb_panel["inactive_contacts"]:
                            context["signatures"][index]["active_contacts"] = len(rfb_panel["active_contacts"][position].difference(rfb_panel["inactive_contacts"][position])) > 0
                        else:
                            context["signatures"][index]["active_contacts"] = True

                    context["signatures"][index]["inactive_contacts"] = False
                    if position in rfb_panel["inactive_contacts"]:
                        if position in rfb_panel["active_contacts"]:
                            context["signatures"][index]["inactive_contacts"] = len(rfb_panel["inactive_contacts"][position].difference(rfb_panel["active_contacts"][position])) > 0
                        else:
                            context["signatures"][index]["inactive_contacts"] = True

                    # CLASS A sequence + property consensus
                    if position in rfb_panel["class_a_positions"]["gpcrdba"][segment]:
                        ca_index = list(rfb_panel["class_a_positions"]["gpcrdba"][segment]).index(position)

                        # Sequence consensus
                        context["signatures"][index]["class_a_aa"] = rfb_panel["class_a_aa"][segment][position][0]
                        context["signatures"][index]["class_a_aa_cons"] = rfb_panel["class_a_aa"][segment][position][2]

                        # Property consensus
                        context["signatures"][index]["class_a_prop"] = rfb_panel["class_a_prop"][segment][i][0]
                        context["signatures"][index]["class_a_prop_cons"] = rfb_panel["class_a_prop"][segment][i][2]

                    # SEQUENCE SIGNATURES
                    for signature_type in ["cah", "cal", "gs", "gio", "gq", "g12"]:
                        if position in rfb_panel["signatures"][signature_type + "_positions"]["gpcrdba"][segment]:
                            ca_index = list(rfb_panel["signatures"][signature_type + "_positions"]["gpcrdba"][segment]).index(position)
                            context["signatures"][index][signature_type + "_score"] = rfb_panel["signatures"][signature_type][segment][ca_index][2]
                            context["signatures"][index][signature_type + "_prop"] = rfb_panel["signatures"][signature_type][segment][ca_index][1]
                            context["signatures"][index][signature_type + "_symb"] = rfb_panel["signatures"][signature_type][segment][ca_index][0]

                    index += 1

        print(str(time.time()) + " Done sending to the template")
        # Human Class A alignment - consensus/conservation
        return context
