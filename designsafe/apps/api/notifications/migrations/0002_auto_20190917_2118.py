# Generated by Django 2.2.5 on 2019-09-17 21:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications_api', '0001_squashed_0003_auto_20180417_2012'),
    ]

    operations = [
        migrations.AlterField(
            model_name='broadcast',
            name='action_link',
            field=models.TextField(default=''),
        ),
        migrations.AlterField(
            model_name='broadcast',
            name='extra',
            field=models.TextField(default=''),
        ),
        migrations.AlterField(
            model_name='broadcast',
            name='message',
            field=models.TextField(default=''),
        ),
        migrations.AlterField(
            model_name='broadcast',
            name='operation',
            field=models.CharField(default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='notification',
            name='action_link',
            field=models.TextField(default=''),
        ),
        migrations.AlterField(
            model_name='notification',
            name='extra',
            field=models.TextField(default=''),
        ),
        migrations.AlterField(
            model_name='notification',
            name='message',
            field=models.TextField(default=''),
        ),
        migrations.AlterField(
            model_name='notification',
            name='operation',
            field=models.CharField(default='', max_length=255),
        ),
    ]
