from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0003_add_domain_to_appusageentry'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='email',
            field=models.EmailField(blank=True, default='', help_text='Employee email for daily timesheet reports', max_length=254),
        ),
    ]
