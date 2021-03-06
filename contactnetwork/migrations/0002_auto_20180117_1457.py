# Generated by Django 2.0.1 on 2018-01-17 13:57

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('contactnetwork', '0001_initial'),
        ('structure', '0001_initial'),
        ('residue', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='interactingresiduepair',
            name='referenced_structure',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='structure.Structure'),
        ),
        migrations.AddField(
            model_name='interactingresiduepair',
            name='res1',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='residue1', to='residue.Residue'),
        ),
        migrations.AddField(
            model_name='interactingresiduepair',
            name='res2',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='residue2', to='residue.Residue'),
        ),
        migrations.CreateModel(
            name='FaceToEdgeInteraction',
            fields=[
                ('aromaticinteraction_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='contactnetwork.AromaticInteraction')),
                ('res1_has_face', models.BooleanField()),
            ],
            options={
                'db_table': 'interaction_aromatic_face_edge',
            },
            bases=('contactnetwork.aromaticinteraction',),
        ),
        migrations.CreateModel(
            name='FaceToFaceInteraction',
            fields=[
                ('aromaticinteraction_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='contactnetwork.AromaticInteraction')),
            ],
            options={
                'db_table': 'interaction_aromatic_face_face',
            },
            bases=('contactnetwork.aromaticinteraction',),
        ),
        migrations.CreateModel(
            name='PiCationInteraction',
            fields=[
                ('aromaticinteraction_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='contactnetwork.AromaticInteraction')),
                ('res1_has_pi', models.BooleanField()),
            ],
            options={
                'db_table': 'interaction_aromatic_pi_cation',
            },
            bases=('contactnetwork.aromaticinteraction',),
        ),
        migrations.CreateModel(
            name='PolarBackboneSidechainInteraction',
            fields=[
                ('polarinteraction_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='contactnetwork.PolarInteraction')),
                ('res1_is_sidechain', models.BooleanField()),
            ],
            options={
                'db_table': 'interaction_polar_backbone_sidechain',
            },
            bases=('contactnetwork.polarinteraction',),
        ),
        migrations.CreateModel(
            name='PolarSidechainSidechainInteraction',
            fields=[
                ('polarinteraction_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='contactnetwork.PolarInteraction')),
            ],
            options={
                'db_table': 'interaction_polar_sidechain_sidechain',
            },
            bases=('contactnetwork.polarinteraction',),
        ),
    ]
