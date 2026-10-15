import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, Consent, Doctor, MedicalRecord, errorMessage, formatDateTime } from './api.service';
import { ExpedienteVistaComponent } from './expediente-vista.component';

/** Flujo 2: el paciente llena su expediente y decide quién lo ve. */
@Component({
  selector: 'midoc-expediente',
  standalone: true,
  imports: [FormsModule, ExpedienteVistaComponent],
  templateUrl: './expediente.component.html'
})
export class ExpedienteComponent implements OnInit {
  private readonly api = inject(ApiService);
  readonly record = signal<MedicalRecord | null>(null);
  readonly consents = signal<Consent[]>([]);
  readonly doctors = signal<Doctor[]>([]);
  readonly message = signal('');
  readonly consentMessage = signal('');
  readonly formatDateTime = formatDateTime;
  readonly sexes = ['FEMENINO', 'MASCULINO', 'OTRO'];
  readonly bloodTypes = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'];

  form = { birthDate: '', sex: '', bloodType: '', allergies: '', chronicConditions: '', medications: '', notes: '' };
  doctorToGrant = '';

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    try {
      const [record, consents, doctors] = await Promise.all([
        this.api.get<MedicalRecord>('/api/records'),
        this.api.get<Consent[]>('/api/consents'),
        this.api.get<Doctor[]>('/api/doctors')
      ]);
      this.record.set(record);
      this.consents.set(consents);
      this.doctors.set(doctors);
      this.form = {
        birthDate: record.birthDate ?? '',
        sex: record.sex ?? '',
        bloodType: record.bloodType ?? '',
        allergies: record.allergies.join(', '),
        chronicConditions: record.chronicConditions.join(', '),
        medications: record.medications.join(', '),
        notes: record.notes ?? ''
      };
    } catch (error) {
      this.message.set(errorMessage(error));
    }
  }

  private list(value: string): string[] {
    return value.split(',').map(item => item.trim()).filter(Boolean);
  }

  async save(): Promise<void> {
    try {
      this.record.set(await this.api.put<MedicalRecord>('/api/records', {
        birthDate: this.form.birthDate || null,
        sex: this.form.sex || null,
        bloodType: this.form.bloodType || null,
        allergies: this.list(this.form.allergies),
        chronicConditions: this.list(this.form.chronicConditions),
        medications: this.list(this.form.medications),
        notes: this.form.notes
      }));
      this.message.set('Expediente actualizado.');
    } catch (error) {
      this.message.set(errorMessage(error));
    }
  }

  async setConsent(doctorId: string, granted: boolean): Promise<void> {
    if (!doctorId) return;
    try {
      await this.api.post('/api/consents', { doctorId, granted });
      this.consentMessage.set(granted ? 'Acceso otorgado.' : 'Acceso revocado: el profesional ya no puede ver tu expediente.');
      this.doctorToGrant = '';
      this.consents.set(await this.api.get<Consent[]>('/api/consents'));
    } catch (error) {
      this.consentMessage.set(errorMessage(error));
    }
  }
}
