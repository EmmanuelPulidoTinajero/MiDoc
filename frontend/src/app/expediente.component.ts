import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
  AccessLogEntry,
  ApiService,
  Consent,
  Doctor,
  MedicalDocument,
  MedicalRecord,
  errorMessage,
  formatDateTime,
} from './api.service';
import {
  DsAlertBannerComponent,
  DsBadgeComponent,
  DsButtonComponent,
  DsCardComponent,
  DsControlDirective,
  DsEmptyStateComponent,
  DsFieldComponent,
  DsModalComponent,
  DsPageHeaderComponent,
  DsSkeletonComponent,
} from './ds';
import { ExpedienteVistaComponent } from './expediente-vista.component';

const ALLOWED_EXTENSIONS = new Set(['pdf', 'jpg', 'jpeg', 'png', 'dcm', 'dicom']);
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

/** Flujo 2: el paciente gestiona su expediente, documentos S3, consentimientos y auditoría de acceso. */
@Component({
  selector: 'midoc-expediente',
  standalone: true,
  imports: [
    FormsModule,
    DsAlertBannerComponent,
    DsBadgeComponent,
    DsButtonComponent,
    DsCardComponent,
    DsControlDirective,
    DsEmptyStateComponent,
    DsFieldComponent,
    DsModalComponent,
    DsPageHeaderComponent,
    DsSkeletonComponent,
    ExpedienteVistaComponent,
  ],
  templateUrl: './expediente.component.html',
})
export class ExpedienteComponent implements OnInit {
  private readonly api = inject(ApiService);
  readonly record = signal<MedicalRecord | null>(null);
  readonly consents = signal<Consent[]>([]);
  readonly doctors = signal<Doctor[]>([]);
  readonly documents = signal<MedicalDocument[]>([]);
  readonly accessLog = signal<AccessLogEntry[]>([]);

  readonly loading = signal(true);
  readonly loadingAccessLog = signal(false);
  readonly uploading = signal(false);
  readonly saving = signal(false);
  readonly deletingDocumentId = signal<string | null>(null);
  readonly updatingConsentId = signal<string | null>(null);

  readonly message = signal('');
  readonly messageTone = signal<'success' | 'danger'>('success');
  readonly documentsMessage = signal('');
  readonly documentsTone = signal<'success' | 'danger'>('success');
  readonly consentMessage = signal('');
  readonly consentTone = signal<'success' | 'danger'>('success');
  readonly accessLogMessage = signal('');

  readonly pendingDeleteDoc = signal<MedicalDocument | null>(null);
  readonly pendingRevokeConsent = signal<Consent | null>(null);

  readonly formatDateTime = formatDateTime;
  readonly sexes = ['FEMENINO', 'MASCULINO', 'OTRO'];
  readonly bloodTypes = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'];

  form = {
    birthDate: '',
    sex: '',
    bloodType: '',
    allergies: '',
    chronicConditions: '',
    medications: '',
    notes: '',
  };
  doctorToGrant = '';

  ngOnInit(): void {
    void this.load();
  }

  scrollToSection(sectionId: string): void {
    document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.message.set('');
    try {
      const [record, consents, doctors] = await Promise.all([
        this.api.get<MedicalRecord>('/api/records'),
        this.api.get<Consent[]>('/api/consents'),
        this.api.get<Doctor[]>('/api/doctors'),
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
        notes: record.notes ?? '',
      };
      await Promise.all([this.loadDocuments(), this.loadAccessLog()]);
    } catch (error) {
      this.messageTone.set('danger');
      this.message.set(errorMessage(error));
    } finally {
      this.loading.set(false);
    }
  }

  async loadDocuments(): Promise<void> {
    try {
      this.documents.set(await this.api.get<MedicalDocument[]>('/api/records/documents'));
      this.documentsMessage.set('');
    } catch (error) {
      this.documentsTone.set('danger');
      this.documentsMessage.set(errorMessage(error));
    }
  }

  async loadAccessLog(): Promise<void> {
    this.loadingAccessLog.set(true);
    this.accessLogMessage.set('');
    try {
      this.accessLog.set(await this.api.getRecordAccessLog());
    } catch (error) {
      this.accessLogMessage.set(errorMessage(error));
    } finally {
      this.loadingAccessLog.set(false);
    }
  }

  async uploadDocument(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
    if (!ALLOWED_EXTENSIONS.has(ext)) {
      this.documentsTone.set('danger');
      this.documentsMessage.set(
        'Formato no compatible. Sube archivos PDF, JPG, PNG o DICOM (.dcm / .dicom).',
      );
      input.value = '';
      return;
    }
    if (file.size <= 0 || file.size > MAX_FILE_SIZE_BYTES) {
      this.documentsTone.set('danger');
      this.documentsMessage.set('El archivo debe pesar entre 1 byte y 10 MB.');
      input.value = '';
      return;
    }

    this.uploading.set(true);
    this.documentsMessage.set('');
    try {
      await this.api.uploadDocument(file);
      this.documentsTone.set('success');
      this.documentsMessage.set('Archivo agregado de forma privada a tu expediente.');
      await this.loadDocuments();
    } catch (error) {
      this.documentsTone.set('danger');
      this.documentsMessage.set(errorMessage(error));
    } finally {
      this.uploading.set(false);
      input.value = '';
    }
  }

  requestDeleteDocument(document: MedicalDocument): void {
    this.pendingDeleteDoc.set(document);
  }

  async confirmDeleteDocument(): Promise<void> {
    const doc = this.pendingDeleteDoc();
    if (!doc || this.deletingDocumentId()) return;
    this.deletingDocumentId.set(doc.id);
    try {
      await this.api.delete(`/api/records/documents/${doc.id}`);
      this.documents.update((items) => items.filter((item) => item.id !== doc.id));
      this.pendingDeleteDoc.set(null);
      this.documentsTone.set('success');
      this.documentsMessage.set(`Se eliminó «${doc.name}» de tu expediente.`);
    } catch (error) {
      this.pendingDeleteDoc.set(null);
      this.documentsTone.set('danger');
      this.documentsMessage.set(errorMessage(error));
    } finally {
      this.deletingDocumentId.set(null);
    }
  }

  formatSize(bytes: number): string {
    return bytes < 1_000_000 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1_000_000).toFixed(1)} MB`;
  }

  private list(value: string): string[] {
    return value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }

  async save(): Promise<void> {
    if (this.saving()) return;
    this.saving.set(true);
    try {
      this.record.set(
        await this.api.put<MedicalRecord>('/api/records', {
          birthDate: this.form.birthDate || null,
          sex: this.form.sex || null,
          bloodType: this.form.bloodType || null,
          allergies: this.list(this.form.allergies),
          chronicConditions: this.list(this.form.chronicConditions),
          medications: this.list(this.form.medications),
          notes: this.form.notes,
        }),
      );
      this.messageTone.set('success');
      this.message.set('Expediente clínico actualizado.');
    } catch (error) {
      this.messageTone.set('danger');
      this.message.set(errorMessage(error));
    } finally {
      this.saving.set(false);
    }
  }

  requestRevokeConsent(consent: Consent): void {
    this.pendingRevokeConsent.set(consent);
  }

  async confirmRevokeConsent(): Promise<void> {
    const consent = this.pendingRevokeConsent();
    if (!consent) return;
    await this.setConsent(consent.doctorId, false);
    this.pendingRevokeConsent.set(null);
  }

  async setConsent(doctorId: string, granted: boolean): Promise<void> {
    if (!doctorId || this.updatingConsentId()) return;
    this.updatingConsentId.set(doctorId);
    try {
      await this.api.post('/api/consents', { doctorId, granted });
      this.consentTone.set('success');
      this.consentMessage.set(
        granted
          ? 'Acceso otorgado al profesional seleccionado.'
          : 'Acceso revocado: el profesional ya no puede consultar tu expediente.',
      );
      this.doctorToGrant = '';
      this.consents.set(await this.api.get<Consent[]>('/api/consents'));
    } catch (error) {
      this.consentTone.set('danger');
      this.consentMessage.set(errorMessage(error));
    } finally {
      this.updatingConsentId.set(null);
    }
  }

  accessRoleLabel(role: string): string {
    if (role === 'CLINICA') return 'Clínica';
    if (role === 'DOCTOR') return 'Doctor(a)';
    return role;
  }

  accessEventLabel(event: string): string {
    if (event.toUpperCase().includes('DOCUMENT')) return 'Consulta de documento';
    return 'Lectura de expediente';
  }
}
